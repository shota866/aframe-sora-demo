from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from ..domain.constants import (
    HEARTBEAT_IDLE_SEC,
    IDLE_STATE_INTERVAL_SEC,
)
from ..domain.vehicle import VehicleModel
from .conductor_state import ControlState, EstopState, HeartbeatState

#状態ペイロードを作成するクラス
class StatePayloadBuilder:
    """Create state payloads that are published over the data channel."""

    def __init__(
        self,
        vehicle: VehicleModel,
        vehicle_lock: threading.Lock,
        control_state: ControlState,
        heartbeat_state: HeartbeatState,
        estop_state: EstopState,
    ) -> None:
        self._vehicle = vehicle
        self._vehicle_lock = vehicle_lock
        self._control_state = control_state
        self._heartbeat_state = heartbeat_state
        self._estop_state = estop_state
        self._state_seq = 0
        self._last_idle_state_emit = 0.0
    
    def reset(self) -> None:
        self._state_seq = 0
        self._last_idle_state_emit = 0.0
    #状態ペイロードを構築するメソッド
    def build(self) -> Dict[str, object]:
        with self._vehicle_lock:
            data = self._vehicle.snapshot()
            ctrl_age = self._vehicle.ctrl_age
            estop_active = self._vehicle.estop_active

        hb_age = self._heartbeat_age()

        now_ms = int(time.time() * 1000.0)
        now_wall = time.time()
        status_ok = True
        status_msg = "ok"
        if hb_age is not None and hb_age > HEARTBEAT_IDLE_SEC:
            status_ok = False
            status_msg = f"hb age {hb_age:.1f}s"
        if ctrl_age > IDLE_STATE_INTERVAL_SEC:
            if now_wall - self._last_idle_state_emit < IDLE_STATE_INTERVAL_SEC:
                return {}
            self._last_idle_state_emit = now_wall
        else:
            self._last_idle_state_emit = now_wall

        if estop_active:
            status_ok = False
            status_msg = "estop"

        payload: Dict[str, object] = {
            "type": "state",
            "seq": self._next_state_seq(),
            "t": now_ms,
            "pose": data["pose"],
            "vel": data["vel"],
            "status": {"ok": status_ok, "msg": status_msg},
            "sim": data["sim"],
        }

        pose = data["pose"]
        vel = data["vel"]
        payload.update(
            {
                "x": pose.get("x"),
                "y": pose.get("z"),
                "theta": pose.get("yaw"),
                "vx": vel.get("vx"),
                "wz": vel.get("wz"),
            }
        )

        if hb_age is not None:
            payload["status"]["hb_age"] = hb_age
        ctrl_latency_ms = self._control_state.get_last_latency_ms()
        if ctrl_latency_ms is not None:
            payload["status"]["ctrl_latency_ms"] = ctrl_latency_ms
        if self._estop_state.is_triggered():
            payload["status"]["estop"] = True

        return payload
    
    def _next_state_seq(self) -> int:
        self._state_seq = (self._state_seq + 1) % (1 << 31)
        return self._state_seq
    
    def _heartbeat_age(self) -> Optional[float]:
        last = self._heartbeat_state.get_last_from_ui()
        if last is None:
            return None
        return time.time() - last
