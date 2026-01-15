from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from ..domain.constants import (
    HEARTBEAT_IDLE_SEC,
    IDLE_STATE_INTERVAL_SEC,
)
from ..domain.control import ControlSnapshot
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
        if ctrl_age > IDLE_STATE_INTERVAL_SEC:
            if now_wall - self._last_idle_state_emit < IDLE_STATE_INTERVAL_SEC:
                return {}
            self._last_idle_state_emit = now_wall
        else:
            self._last_idle_state_emit = now_wall

        pose_world = data["pose"]
        vel_world = data["vel"]
        planar_pose = {
            "x": pose_world.get("x"),
            "y": pose_world.get("z"),
            "heading": pose_world.get("yaw"),
        }
        planar_velocity = {
            "linear": vel_world.get("vx"),
            "angular": vel_world.get("wz"),
        }

        status_msg = "ok"
        status_ok = True
        status_payload: Dict[str, object] = {"ok": status_ok, "msg": status_msg}

        if hb_age is not None:
            status_payload["hb_age_ms"] = hb_age * 1000.0
            if hb_age > HEARTBEAT_IDLE_SEC:
                status_ok = False
                status_msg = f"hb age {hb_age:.1f}s"

        ctrl_latency_ms = self._control_state.get_last_latency_ms()
        if ctrl_latency_ms is not None:
            status_payload["ctrl_latency_ms"] = ctrl_latency_ms

        if estop_active or self._estop_state.is_triggered():
            status_ok = False
            status_msg = "estop"
            status_payload["estop"] = True

        status_payload["ok"] = status_ok
        status_payload["msg"] = status_msg

        payload: Dict[str, object] = {
            "type": "state",
            "seq": self._next_state_seq(),
            "sent_at_ms": now_ms,
            "pose": planar_pose,
            "velocity": planar_velocity,
            "status": status_payload,
            "step": {"dt_sec": data["sim"].get("dt")},
        }

        last_ctrl_snapshot = self._control_state.get_last_ctrl()
        last_ctrl_payload = self._build_last_ctrl_payload(last_ctrl_snapshot)
        if last_ctrl_payload:
            payload["last_ctrl"] = last_ctrl_payload

        return payload
    
    def _next_state_seq(self) -> int:
        self._state_seq = (self._state_seq + 1) % (1 << 31)
        return self._state_seq
    
    def _heartbeat_age(self) -> Optional[float]:
        last = self._heartbeat_state.get_last_from_ui()
        if last is None:
            return None
        return time.time() - last

    def _build_last_ctrl_payload(
        self,
        snapshot: Optional[ControlSnapshot],
    ) -> Optional[Dict[str, object]]:
        if snapshot is None:
            return None

        payload: Dict[str, object] = {
            "seq": snapshot.seq,
            "mode": snapshot.mode,
            "command": {
                "throttle": snapshot.throttle,
                "steer": snapshot.steer,
                "brake": snapshot.brake,
            },
        }

        if snapshot.client_timestamp_ms is not None:
            payload["sent_at_ms"] = int(snapshot.client_timestamp_ms)

        manager_recv_at_ms = snapshot.manager_recv_at_ms
        if manager_recv_at_ms is None:
            recv_wall = self._control_state.get_last_recv_wall()
            if recv_wall is not None:
                manager_recv_at_ms = int(recv_wall * 1000.0)
        if manager_recv_at_ms is not None:
            payload["manager_recv_at_ms"] = manager_recv_at_ms

        latency_ms = self._control_state.get_last_latency_ms()
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms

        return payload
