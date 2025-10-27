from __future__ import annotations

import math
from typing import Dict, Optional

from .constants import CTRL_DAMP_SEC, CTRL_HOLD_SEC, PHYSICS_RATE_HZ
from .control import ControlSnapshot, clamp, wrap_angle


class VehicleModel:
    """Planar vehicle integrator suitable for network replay."""

    MAX_SPEED = 20.0  # m/s
    MAX_ACCEL = 9.0  # m/s^2 forward/back
    BRAKE_DECEL = 14.0
    COAST_DECEL = 2.0
    IDLE_DECEL = 1.5
    YAW_RATE_MAX = 2.5  # rad/s
    YAW_SLEW = 6.0  # rad/s^2
    ANGULAR_DAMP = 4.0

    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.yaw = 0.0
        self.vx = 0.0
        self.wz = 0.0
        self._last_dt = 1.0 / PHYSICS_RATE_HZ
        self._last_ctrl_age = float("inf")
        self._estop_active = False

    #コマンド情報から車両の状態を計算して更新するメソッド
    def step(self, ctrl: Optional[ControlSnapshot], dt: float, now: float) -> None:
        self._last_dt = dt
        throttle = steer = brake = 0.0
        age = float("inf")
        if ctrl:
            age = ctrl.age(now)
            if age <= CTRL_HOLD_SEC:
                throttle = ctrl.throttle
                steer = ctrl.steer
                brake = ctrl.brake
            else:
                decay = clamp((age - CTRL_HOLD_SEC) / CTRL_DAMP_SEC, 0.0, 1.0)
                throttle = ctrl.throttle * (1.0 - decay)
                steer = ctrl.steer * (1.0 - decay)
                brake = max(ctrl.brake, decay)
        self._last_ctrl_age = age

        if self._estop_active:
            throttle = 0.0
            brake = 1.0

        accel = throttle * self.MAX_ACCEL#前進/後退の加速度を計算
        if math.isclose(throttle, 0.0, abs_tol=1e-3):
            if abs(self.vx) > 1e-3:
                accel -= math.copysign(self.COAST_DECEL, self.vx)
            else:
                accel = 0.0
        if brake > 0.0 and abs(self.vx) > 1e-3:
            accel -= math.copysign(self.BRAKE_DECEL * brake, self.vx)
        if not ctrl and not self._estop_active:
            if abs(self.vx) > 1e-3:
                accel -= math.copysign(self.IDLE_DECEL, self.vx)
            else:
                self.vx = 0.0

        self.vx += accel * dt
        if abs(self.vx) < 1e-3:
            self.vx = 0.0
        self.vx = clamp(self.vx, -self.MAX_SPEED, self.MAX_SPEED)

        target_wz = steer * self.YAW_RATE_MAX
        slew = self.YAW_SLEW * dt
        if ctrl:#操舵入力がある場合、目標角速度に向けて角速度を変化させる
            delta = clamp(target_wz - self.wz, -slew, slew)
            self.wz += delta
        else:#3操舵入力がない場合、角速度を減衰させる
            damping = clamp(self.ANGULAR_DAMP * dt, 0.0, 1.0)  
            self.wz *= 1.0 - damping
        if abs(self.wz) < 1e-3:
            self.wz = 0.0

        yaw_now = wrap_angle(self.yaw + self.wz * dt)
        heading_x = math.sin(yaw_now)
        heading_z = math.cos(yaw_now)
        self.x += self.vx * heading_x * dt
        self.z += self.vx * heading_z * dt
        self.yaw = yaw_now

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        return {
            "pose": {"x": self.x, "y": self.y, "z": self.z, "yaw": self.yaw},
            "vel": {"vx": self.vx, "wz": self.wz},
            "sim": {"dt": self._last_dt},
        }

    @property
    def ctrl_age(self) -> float:
        return self._last_ctrl_age

    def estop(self) -> None:
        self._estop_active = True
        self.vx = 0.0
        self.wz = 0.0

    def clear_estop(self) -> None:
        self._estop_active = False

    @property
    def estop_active(self) -> bool:
        return self._estop_active


__all__ = ["VehicleModel"]

