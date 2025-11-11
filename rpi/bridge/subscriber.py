from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Optional

from .converter import CommandConverter
from .publisher import CmdVelPublisher

LOGGER = logging.getLogger(__name__)


class CommandSubscriber:
    """Consume state payloads and emit cmd_vel via converter + publisher."""

    def __init__(
        self,
        publisher: CmdVelPublisher,
        converter: CommandConverter,
        *,
        command_timeout_sec: float,
    ) -> None:
        self._publisher = publisher
        self._converter = converter
        self._command_timeout_sec = command_timeout_sec

        self._last_seq: Optional[int] = None
        self._last_publish_wall = 0.0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def process_payload(self, payload: Dict[str, object]) -> None:
        last_ctrl = payload.get("last_ctrl")
        if not isinstance(last_ctrl, dict):
            return

        seq = last_ctrl.get("seq")
        if seq is None:
            return

        with self._lock:
            if self._last_seq == seq:
                self._last_publish_wall = time.time()
                return
            self._last_seq = seq

        command = last_ctrl.get("command") or {}
        throttle = float(command.get("throttle") or 0.0)
        steer = float(command.get("steer") or 0.0)
        brake = float(command.get("brake") or 0.0)

        status = payload.get("status") or {}
        estop_active = bool(status.get("estop")) or not bool(status.get("ok", True))

        if estop_active:
            LOGGER.warning("estop active -> forcing cmd_vel=0")

        linear, angular = self._converter.to_velocity(
            throttle,
            steer,
            brake,
            estop_active=estop_active,
        )
        LOGGER.debug(
            "publishing cmd_vel: linear=%.3f angular=%.3f", linear, angular
        )
        self._publisher.publish(linear, angular)

        with self._lock:
            self._last_publish_wall = time.time()

    def close(self) -> None:
        self._stop_event.set()
        self._watchdog_thread.join(timeout=1.0)

    def _watchdog_loop(self) -> None:
        while not self._stop_event.wait(timeout=0.1):
            if self._command_timeout_sec <= 0:
                continue

            with self._lock:
                last_publish = self._last_publish_wall
            if last_publish <= 0:
                continue

            if time.time() - last_publish >= self._command_timeout_sec:
                LOGGER.warning(
                    "no command update for %.2fs -> forcing cmd_vel=0",
                    self._command_timeout_sec,
                )
                self._publisher.publish_zero()
                with self._lock:
                    self._last_publish_wall = 0.0

def main() -> None:
    cms  = CommandSubscriber(
        publisher=CmdVelPublisher(),
        converter=CommandConverter(),
        command_timeout_sec=1.0,
    )

if __name__ == "__main__":
    main()