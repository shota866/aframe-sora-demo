from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


COMMAND_PRESETS: Dict[str, Tuple[float, float, float]] = {
    # command -> (throttle, steer, brake)
    "IDLE": (0.0, 0.0, 0.4),
    "UP": (1.0, 0.0, 0.0),
    "DOWN": (-1.0, 0.0, 0.0),
    "LEFT": (0.0, -1.0, 0.0),
    "RIGHT": (0.0, 1.0, 0.0),
}


@dataclass
class CommandConverter:
    """
    Map UI command strings (UP/DOWN/LEFT/RIGHT/IDLE) or raw throttle/steer/brake
    into linear/angular speeds.
    """

    max_linear_speed: float
    max_angular_speed: float
    brake_threshold: float

    def to_velocity(
        self,
        command: str | None = None,
        *,
        throttle: float | None = None,
        steer: float | None = None,
        brake: float | None = None,
        estop_active: bool = False,
    ) -> tuple[float, float]:
        """
        Return (linear, angular) command in SI units.
        - If command is provided, use UI presets.
        - Otherwise fall back to raw throttle/steer/brake values.
        """
        # Normalise inputs
        throttle_val = throttle if throttle is not None else 0.0
        steer_val = steer if steer is not None else 0.0
        brake_val = brake if brake is not None else 0.0

        if command:
            preset = COMMAND_PRESETS.get(command.upper())
            if preset:
                throttle_val, steer_val, brake_val = preset

        if estop_active or brake_val >= self.brake_threshold:
            return 0.0, 0.0

        throttle_clamped = _clamp(throttle_val, -1.0, 1.0)
        steer_clamped = _clamp(steer_val, -1.0, 1.0)

        linear = throttle_clamped * self.max_linear_speed
        angular = steer_clamped * self.max_angular_speed
        return linear, angular
