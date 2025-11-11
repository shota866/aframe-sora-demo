from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommandConverter:
    """Map throttle / steer / brake into linear and angular speeds."""

    max_linear_speed: float
    max_angular_speed: float
    brake_threshold: float

    def to_velocity(
        self,
        throttle: float,
        steer: float,
        brake: float,
        *,
        estop_active: bool,
    ) -> tuple[float, float]:
        """Return (linear, angular) command in SI units."""
        if estop_active or brake >= self.brake_threshold:
            return 0.0, 0.0

        throttle_clamped = max(min(throttle, 1.0), -1.0)
        steer_clamped = max(min(steer, 1.0), -1.0)

        linear = throttle_clamped * self.max_linear_speed
        angular = steer_clamped * self.max_angular_speed
        return linear, angular
