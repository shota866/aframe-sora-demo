from __future__ import annotations

import json
import logging
import threading
import time
from typing import Dict

from ..adapters.dc_manager import DataChannelManager
from ..adapters.sora_base import create_sora_instance
from ..config import ServerConfig
from ..domain.vehicle import VehicleModel
from .conductor_connection import ConductorConnectionManager
from .conductor_handlers import DataChannelMessageHandler
from .conductor_state import ControlState, EstopState, HeartbeatState, StatsTracker
from .loops import HeartbeatLoop, PhysicsLoop, StateLoop, StatLoop
from .state_payload import StatePayloadBuilder

LOGGER = logging.getLogger("manager")


class Conductor:
    """Coordinate domain logic with Sora transport."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._sora = create_sora_instance()
        self._dc = DataChannelManager(config.ctrl_label, config.state_label)

        self._stop_event = threading.Event()

        self._vehicle = VehicleModel()
        self._vehicle_lock = threading.Lock()

        self._control_state = ControlState()
        self._heartbeat_state = HeartbeatState()
        self._estop_state = EstopState()
        self._stats_tracker = StatsTracker()

        self._payload_builder = StatePayloadBuilder(
            vehicle=self._vehicle,
            vehicle_lock=self._vehicle_lock,
            control_state=self._control_state,
            heartbeat_state=self._heartbeat_state,
            estop_state=self._estop_state,
        )

        self._message_handler = DataChannelMessageHandler(
            ctrl_label=config.ctrl_label,
            control_state=self._control_state,
            heartbeat_state=self._heartbeat_state,
            estop_state=self._estop_state,
            vehicle=self._vehicle,
            vehicle_lock=self._vehicle_lock,
            stats_tracker=self._stats_tracker,
        )

        self._connection_manager = ConductorConnectionManager(
            config=self.config,
            sora=self._sora,
            dc_manager=self._dc,
            stop_event=self._stop_event,
            on_message=self._message_handler.handle,
        )

        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------ lifecycle
    # メインループを開始するメソッド
    def start(self) -> None:
        self._stop_event.clear()#is_setをFalseにする
        self._payload_builder.reset()
        self._connection_manager.start()

        physics_loop = PhysicsLoop(
            stop_event=self._stop_event,
            control_state=self._control_state,
            vehicle=self._vehicle,
            vehicle_lock=self._vehicle_lock,
        )
        #状態ペイロードを送信するループ
        state_loop = StateLoop(
            stop_event=self._stop_event,
            connection_alive=self._connection_manager.connection_alive,
            dc_manager=self._dc,
            state_label=self.config.state_label,
            payload_builder=self._payload_builder,
            send_state=self._send_state,
        )
        # HBを送信するループ
        heartbeat_loop = HeartbeatLoop(
            stop_event=self._stop_event,
            vehicle=self._vehicle,
            vehicle_lock=self._vehicle_lock,
            send_heartbeat=self._send_heartbeat,
        )
        #ステータスを送信するループ
        stat_loop = StatLoop(
            stop_event=self._stop_event,
            stats_tracker=self._stats_tracker,
        )

        self._threads = [
            threading.Thread(target=self._connection_manager.run, name="sora-conn", daemon=True),
            threading.Thread(target=physics_loop.run, name="physics", daemon=True),
            threading.Thread(target=state_loop.run, name="state", daemon=True),
            threading.Thread(target=heartbeat_loop.run, name="heartbeat", daemon=True),
            threading.Thread(target=stat_loop.run, name="stats", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
# メインループを停止するメソッド
    def stop(self) -> None:
        self._stop_event.set()#is_setをTrueにする
        self._connection_manager.shutdown()
        self._dc.detach()
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads.clear()

    def trigger_estop(self) -> None:
        LOGGER.warning("estop triggered locally")
        with self._vehicle_lock:
            self._vehicle.estop()
        self._estop_state.trigger()

    def wait_forever(self) -> None:
        try:
            while not self._stop_event.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            LOGGER.info("interrupt received; stopping")
            self.stop()

    # ------------------------------------------------------------------ helpers
    def _log_state_send(self, payload: str, size: int) -> None:
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "sending state label=%s size=%d payload=%s",
                self.config.state_label,
                size,
                payload,
            )

    def _send_state(self, obj: Dict[str, object]) -> None:
        if not obj:
            return
        payload_json = json.dumps(obj, separators=(",", ":"))
        preview = payload_json
        if len(preview) > 512:
            preview = f"{preview[:512]}...(truncated)"
        self._log_state_send(preview, len(payload_json))
        data = payload_json.encode("utf-8")
        if self._connection_manager.send_data(self.config.state_label, data):
            self._stats_tracker.inc_state_sent()
        else:
            LOGGER.debug("state send failed label=%s", self.config.state_label)

    def _send_heartbeat(self) -> None:
        if not self._connection_manager.connection_alive.is_set():
            return
        payload = json.dumps(
            {
                "type": "hb",
                "role": "server",
                "t": int(time.time() * 1000.0),
                "label": self.config.state_label,
            }
        ).encode("utf-8")
        self._connection_manager.send_data(self.config.state_label, payload)


__all__ = ["Conductor"]
