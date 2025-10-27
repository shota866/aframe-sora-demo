from __future__ import annotations

import threading
from typing import Optional, Tuple

from ..domain.control import ControlSnapshot


class ControlState:
    """Store the latest control snapshot and related metadata."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_ctrl: Optional[ControlSnapshot] = None
        self._last_ctrl_latency_ms: Optional[float] = None
        self._last_ctrl_recv_wall: Optional[float] = None

    def update_if_new(
        self,
        snapshot: ControlSnapshot,
        latency_ms: Optional[float],
        recv_wall: Optional[float],
    ) -> bool:
        """Update control snapshot when the sequence number advances."""
        with self._lock:
            if self._last_ctrl and snapshot.seq <= self._last_ctrl.seq:
                return False
            self._last_ctrl = snapshot
            self._last_ctrl_latency_ms = latency_ms
            self._last_ctrl_recv_wall = recv_wall
            return True

    # 最新のコマンド情報を取得するメソッド
    def get_last_ctrl(self) -> Optional[ControlSnapshot]:
        with self._lock:
            return self._last_ctrl

    def get_last_latency_ms(self) -> Optional[float]:
        with self._lock:
            return self._last_ctrl_latency_ms

    def get_last_recv_wall(self) -> Optional[float]:
        with self._lock:
            return self._last_ctrl_recv_wall


class HeartbeatState:
    """Track the timestamp of the latest heartbeat received from the UI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_from_ui: Optional[float] = None

    def mark_from_ui(self, timestamp: float) -> None:
        with self._lock:
            self._last_from_ui = timestamp

    def get_last_from_ui(self) -> Optional[float]:
        with self._lock:
            return self._last_from_ui


class EstopState:
    """Represent the estop flag that can be set by local or remote triggers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._triggered = False

    def trigger(self) -> None:
        with self._lock:
            self._triggered = True

    def clear(self) -> None:
        with self._lock:
            self._triggered = False

    def is_triggered(self) -> bool:
        with self._lock:
            return self._triggered


class StatsTracker:
    """Maintain lightweight counters for diagnostics logging."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ctrl_recv = 0
        self._ctrl_drop = 0
        self._state_sent = 0

    def inc_ctrl_recv(self) -> None:
        with self._lock:
            self._ctrl_recv += 1

    def inc_ctrl_drop(self) -> None:
        with self._lock:
            self._ctrl_drop += 1

    def inc_state_sent(self) -> None:
        with self._lock:
            self._state_sent += 1

    def snapshot(self) -> Tuple[int, int, int]:
        with self._lock:
            return (self._ctrl_recv, self._ctrl_drop, self._state_sent)
