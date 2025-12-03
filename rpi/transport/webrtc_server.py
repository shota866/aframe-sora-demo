from __future__ import annotations

import json
import logging
import threading
from typing import Iterable, Optional

from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode

from . import ControlServerTransport, CtrlCallback

LOGGER = logging.getLogger(__name__)


class WebRTCServerTransport(ControlServerTransport):
    """Sora-based ctrl receiver (UI -> RPi) using the strategy interface."""

    def __init__(
        self,
        *,
        signaling_urls: Iterable[str],
        channel_id: str,
        ctrl_label: str,
        metadata: Optional[dict] = None,
        debug: bool = False,
        connect_timeout: float = 10.0,
    ) -> None:
        self.signaling_urls = list(signaling_urls)
        self.channel_id = channel_id
        self.ctrl_label = ctrl_label
        self.metadata = metadata
        self.debug = debug
        self.connect_timeout = connect_timeout

        self._sora = Sora()
        self._conn: Optional[SoraConnection] = None

        self._connected = threading.Event()
        self._closed = threading.Event()
        self._ctrl_ready = threading.Event()
        self._lock = threading.Lock()
        self._on_ctrl_cb: Optional[CtrlCallback] = None

    def on_ctrl(self, callback: CtrlCallback) -> None:
        self._on_ctrl_cb = callback

    def connect(self) -> None:
        if not self.signaling_urls:
            raise ValueError("signaling_urls must not be empty")

        LOGGER.info(
            "connecting to Sora: urls=%s channel=%s ctrl_label=%s",
            self.signaling_urls,
            self.channel_id,
            self.ctrl_label,
        )

        conn = self._sora.create_connection(
            signaling_urls=self.signaling_urls,
            role="sendrecv",
            channel_id=self.channel_id,
            metadata=self.metadata,
            audio=False,
            video=True,
            data_channel_signaling=True,
            data_channels=[
                {"label": self.ctrl_label, "direction": "recvonly", "ordered": True},
            ],
        )

        conn.on_set_offer = self._on_set_offer
        conn.on_notify = self._on_notify
        conn.on_data_channel = self._on_data_channel
        conn.on_message = self._on_message
        conn.on_disconnect = self._on_disconnect

        with self._lock:
            self._conn = conn

        conn.connect()

        if not self._connected.wait(timeout=self.connect_timeout):
            raise TimeoutError("Sora connection timeout")
        LOGGER.info("Sora connected")

    def close(self) -> None:
        with self._lock:
            conn = self._conn
            self._conn = None
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                LOGGER.debug("disconnect raised", exc_info=True)
        self._closed.set()

    def is_closed(self) -> bool:
        return self._closed.is_set()

    # ------------------------------------------------------------------ Callbacks
    def _on_set_offer(self, raw: str) -> None:
        if self.debug:
            LOGGER.debug("set_offer: %s", raw)

    def _on_notify(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("notify: could not decode JSON: %s", raw)
            return

        event_type = data.get("event_type")
        if data.get("type") == "notify" and event_type == "connection.created":
            LOGGER.info("connection created: connection_id=%s", data.get("connection_id"))
            self._connected.set()
        elif self.debug:
            LOGGER.debug("notify: %s", data)

    def _on_data_channel(self, label: str) -> None:
        if label == self.ctrl_label:
            LOGGER.info("ctrl channel ready: %s", label)
            self._ctrl_ready.set()
        else:
            LOGGER.info("datachannel event: %s", label)

    def _on_message(self, label: str, data: bytes) -> None:
        if label != self.ctrl_label:
            return

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            LOGGER.warning("ctrl message not utf-8; dropping")
            return

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            LOGGER.warning("ctrl message invalid JSON; dropping: %s", text)
            return

        msg_type = str(payload.get("type") or payload.get("t") or "").lower()
        if msg_type == "hb":
            LOGGER.debug("heartbeat received on ctrl channel")
            return
        if msg_type not in {"cmd", "ctrl"}:
            if self.debug:
                LOGGER.debug("ignoring non-ctrl payload: %s", payload)
            return

        LOGGER.info("recv ctrl label=%s raw=%s", label, payload)
        callback = self._on_ctrl_cb
        if callback is not None:
            try:
                callback(payload)
            except Exception:  # noqa: BLE001
                LOGGER.exception("ctrl callback raised")

    def _on_disconnect(self, code: SoraSignalingErrorCode, msg: str) -> None:
        LOGGER.info("Sora disconnected: code=%s msg=%s", code, msg)
        self._closed.set()
