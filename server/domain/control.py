from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional

from .constants import CTRL_DAMP_SEC, CTRL_HOLD_SEC


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def wrap_angle(rad: float) -> float:
    while rad > math.pi:
        rad -= math.tau
    while rad <= -math.pi:
        rad += math.tau
    return rad


SIMPLE_COMMAND_PRESETS: Dict[str, Dict[str, float]] = {
    "IDLE": {"throttle": 0.0, "steer": 0.0, "brake": 0.4},
    "UP": {"throttle": 0.9, "steer": 0.0, "brake": 0.0},
    "DOWN": {"throttle": -0.5, "steer": 0.0, "brake": 0.0},
    "LEFT": {"throttle": 0.6, "steer": -0.7, "brake": 0.0},
    "RIGHT": {"throttle": 0.6, "steer": 0.7, "brake": 0.0},
}


@dataclass
class ControlSnapshot:
    seq: int
    throttle: float
    steer: float
    brake: float
    mode: str
    received_at: float
    client_timestamp_ms: Optional[int]

    def age(self, now: float) -> float:
        return now - self.received_at


__all__ = [
    "ControlSnapshot",
    "SIMPLE_COMMAND_PRESETS",
    "clamp",
    "wrap_angle",
    "CTRL_HOLD_SEC",
    "CTRL_DAMP_SEC",
]

