
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Optional

from sora_sdk import SoraConnection, SoraSignalingErrorCode

from ..adapters.dc_manager import DataChannelManager
from ..adapters.sora_connection import (
    SoraConnectionConfig,
    SoraEventHandlers,
    create_connection,
)
from ..config import ServerConfig

LOGGER = logging.getLogger("manager")

#接続管理クラス
class ConductorConnectionManager:
    """Manage the lifecycle of the Sora connection for the Conductor."""

    def __init__(
        self,
        config: ServerConfig,
        sora,
        dc_manager: DataChannelManager,
        stop_event: threading.Event,
        on_message: Callable[[str, bytes], None],
    ) -> None:
        self._config = config
        self._sora = sora
        self._dc = dc_manager
        self._stop_event = stop_event
        self._message_callback = on_message

        self._reconnect_event = threading.Event()
        self._connected_event = threading.Event()
        self._disconnected_event = threading.Event()
        self._connection_alive = threading.Event()

        self._conn_lock = threading.Lock()
        self._conn: Optional[SoraConnection] = None
        self._connection_id: Optional[str] = None

    def start(self) -> None:
        self._reconnect_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._reconnect_event.wait()
            if self._stop_event.is_set():
                break
            self._reconnect_event.clear()
            try:
                #sora SDKに対して、このイベントが起きたらこれらの関数を呼び出すように登録
                handlers = SoraEventHandlers(
                    on_set_offer=self._on_set_offer,
                    on_notify=self._on_notify,
                    on_data_channel=self._on_data_channel,
                    on_message=self._on_message,
                    on_disconnect=self._on_disconnect,
                )
                conn = create_connection(
                    self._sora,
                    SoraConnectionConfig(
                        signaling_urls=self._config.signaling_urls,
                        channel_id=self._config.channel_id,
                        ctrl_label=self._config.ctrl_label,
                        state_label=self._config.state_label,
                        metadata=self._config.metadata,
                    ),
                    handlers,
                )
                with self._conn_lock:
                    self._conn = conn
                self._dc.attach(conn)
                self._connection_id = None
                self._connected_event.clear()
                self._connection_alive.clear()
                self._disconnected_event.clear()

                LOGGER.info("connecting to Sora %s", self._config.signaling_urls)
                LOGGER.info("channel_id %s", self._config.channel_id)
                conn.connect()
                if not self._connected_event.wait(timeout=10.0):
                    LOGGER.error("Sora connect timeout")
                    conn.disconnect()
                    time.sleep(2.0)
                    self._reconnect_event.set()
                    continue

                self._connection_alive.set()
                LOGGER.info("Sora connected: connection_id=%s", self._connection_id)
                while not self._stop_event.is_set():
                    if self._disconnected_event.wait(timeout=0.5):
                        break
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "connection loop error; signaling_urls=%s metadata=%s",
                    self._config.signaling_urls,
                    self._config.metadata,
                )
                time.sleep(2.0)
            finally:
                with self._conn_lock:
                    conn = self._conn
                    self._conn = None
                self._dc.detach()
                if conn is not None:
                    try:
                        conn.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                self._connection_alive.clear()
                if not self._stop_event.is_set():
                    time.sleep(1.0)
                    self._reconnect_event.set()

    def shutdown(self) -> None:
        self._disconnected_event.set()
        self._reconnect_event.set()
        with self._conn_lock:
            conn = self._conn
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass
    # メッセージを送信するメソッド
    def send_data(self, label: str, data: bytes) -> bool:
        with self._conn_lock:
            conn = self._conn
        if not conn:
            return False
        try:
            conn.send_data_channel(label, data)
            return True
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug(
                "send failed just before disconnect: label=%s err=%s",
                label,
                exc,
            )
            return False

    @property
    def connection_alive(self) -> threading.Event:
        return self._connection_alive
    #接続の正当性を確認するメソッド
    def _on_set_offer(self, conn: SoraConnection, raw: str) -> None:
        if not self._is_current_conn(conn):
            return
        msg = json.loads(raw)
        if msg.get("type") == "offer":
            self._connection_id = msg.get("connection_id")

    def _on_notify(self, conn: SoraConnection, raw: str) -> None:
        if not self._is_current_conn(conn):
            return
        msg = json.loads(raw)
        if (
            msg.get("type") == "notify"
            and msg.get("event_type") == "connection.created"
            and msg.get("connection_id") == self._connection_id
        ):
            self._connected_event.set()
    # データチャネル準備完了時のメソッド
    def _on_data_channel(self, conn: SoraConnection, label: str) -> None:
        if not self._is_current_conn(conn):
            return
        self._dc.mark_ready(label)
        LOGGER.info("data channel ready: %s", label)
    # データチャネルメッセージ受信時のメソッド
    def _on_message(self, conn: SoraConnection, label: str, data: bytes) -> None:
        if not self._is_current_conn(conn):
            return
        self._message_callback(label, data)

    def _on_disconnect(
        self,
        conn: SoraConnection,
        code: SoraSignalingErrorCode,
        msg: str,
    ) -> None:
        if not self._is_current_conn(conn):
            return
        LOGGER.warning(
            "Sora disconnected: conn=%s code=%s msg=%s url_list=%s",
            conn,
            code,
            msg,
            self._config.signaling_urls,
        )
        self._connection_alive.clear()
        self._disconnected_event.set()

    def _is_current_conn(self, conn: SoraConnection) -> bool:
        with self._conn_lock:
            return conn is self._conn
