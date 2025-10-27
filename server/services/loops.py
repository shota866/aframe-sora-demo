from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Dict

from ..adapters.dc_manager import DataChannelManager
from ..domain.constants import (
    CTRL_DAMP_SEC,
    CTRL_HOLD_SEC,
    HEARTBEAT_IDLE_SEC,
    HEARTBEAT_SEC,
    PHYSICS_RATE_HZ,
    STATE_RATE_HZ,
)
from ..domain.vehicle import VehicleModel
from .conductor_state import ControlState, StatsTracker
from .state_payload import StatePayloadBuilder

LOGGER = logging.getLogger("manager")


class PhysicsLoop:#
    """Advance the vehicle model at the physics simulation rate."""

    def __init__(
        self,
        stop_event: threading.Event,
        control_state: ControlState,
        vehicle: VehicleModel,
        vehicle_lock: threading.Lock,
        rate_hz: float = PHYSICS_RATE_HZ,
    ) -> None:
        self._stop_event = stop_event
        self._control_state = control_state
        self._vehicle = vehicle
        self._vehicle_lock = vehicle_lock
        self._target_dt = 1.0 / rate_hz

    def run(self) -> None:
        last = time.perf_counter()
        while not self._stop_event.is_set():
            now = time.perf_counter()
            dt = now - last
            if dt <= 0.0:
                dt = self._target_dt
            last = now
            ctrl = self._control_state.get_last_ctrl()#最新のコマンド情報を取得
            with self._vehicle_lock:
                self._vehicle.step(ctrl, dt, now)#車両の状態を更新
            elapsed = time.perf_counter() - now
            sleep_for = self._target_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

#状態を送信するループ
class StateLoop:
    """Publish vehicle state to the UI over the data channel."""

    def __init__(
        self,
        stop_event: threading.Event,
        connection_alive: threading.Event,
        dc_manager: DataChannelManager,
        state_label: str,
        payload_builder: StatePayloadBuilder,
        send_state: Callable[[Dict[str, object]], None],
        rate_hz: float = STATE_RATE_HZ,
    ) -> None:
        self._stop_event = stop_event
        self._connection_alive = connection_alive
        self._dc_manager = dc_manager
        self._state_label = state_label
        self._payload_builder = payload_builder
        self._send_state = send_state
        self._target_dt = 1.0 / rate_hz

    def run(self) -> None:
        while not self._stop_event.is_set():
            start = time.perf_counter()
            if self._connection_alive.is_set() and self._dc_manager.is_ready(self._state_label):
                payload = self._payload_builder.build()
                if payload:
                    self._send_state(payload)
            elapsed = time.perf_counter() - start
            sleep_for = self._target_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

# Heartbeat送信ループ
class HeartbeatLoop:
    """Emit heartbeats to the UI while monitoring control activity."""

    def __init__(
        self,
        stop_event: threading.Event,
        vehicle: VehicleModel,
        vehicle_lock: threading.Lock,
        send_heartbeat: Callable[[], None],
    ) -> None:
        self._stop_event = stop_event
        self._vehicle = vehicle
        self._vehicle_lock = vehicle_lock
        self._send_heartbeat = send_heartbeat
        self._last_hb_sent = time.time()

    def run(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            with self._vehicle_lock:
                ctrl_age = self._vehicle.ctrl_age
            idle = math.isinf(ctrl_age) or ctrl_age > CTRL_HOLD_SEC + CTRL_DAMP_SEC
            interval = HEARTBEAT_IDLE_SEC if idle else HEARTBEAT_SEC
            if now - self._last_hb_sent >= interval:
                self._send_heartbeat()
                self._last_hb_sent = now
            time.sleep(0.1)

#ステータス送信ループ
class StatLoop:
    """Log lightweight counters for diagnostics."""

    def __init__(self, stop_event: threading.Event, stats_tracker: StatsTracker) -> None:
        self._stop_event = stop_event
        self._stats_tracker = stats_tracker

    def run(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(5.0)
            ctrl_recv, ctrl_drop, state_sent = self._stats_tracker.snapshot()
            LOGGER.debug(
                "stats ctrl_recv=%s ctrl_drop=%s state_sent=%s",
                ctrl_recv,
                ctrl_drop,
                state_sent,
            )
