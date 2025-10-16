from __future__ import annotations

import threading
from typing import Dict, Optional

from sora_sdk import SoraConnection


class DataChannelManager:
    """Track data-channel readiness and provide guarded send helpers."""

    def __init__(self, ctrl_label: str, state_label: str) -> None:
        self._ctrl_label = ctrl_label
        self._state_label = state_label
        self._ready: Dict[str, bool] = {
            ctrl_label: False,
            state_label: False,
        }
        self._conn: Optional[SoraConnection] = None
        self._lock = threading.Lock()

    def attach(self, conn: SoraConnection) -> None:
        with self._lock:
            self._conn = conn
            self._ready = {self._ctrl_label: False, self._state_label: False}

    def detach(self) -> None:
        with self._lock:
            self._conn = None
            self._ready = {self._ctrl_label: False, self._state_label: False}

    def mark_ready(self, label: str) -> None:
        with self._lock:
            if label in self._ready:
                self._ready[label] = True

    def is_ready(self, label: str) -> bool:
        with self._lock:
            return bool(self._ready.get(label))

    def get_connection(self) -> Optional[SoraConnection]:
        with self._lock:
            return self._conn


__all__ = ["DataChannelManager"]

