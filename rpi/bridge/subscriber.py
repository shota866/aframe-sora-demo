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

    def process_ctrl_payload(self, payload: Dict[str, object]) -> None:
        """
        Handle UI -> rpi ctrl payloads.
        Expected shape: {"t":"ctrl","seq":123,"command":"UP"} or
        {"t":"ctrl","seq":123,"cmd":{"throttle":0.5,"steer":0,"brake":0}}.
        """
        seq = payload.get("seq")
        command_raw = payload.get("command")
        cmd_obj = payload.get("cmd") if isinstance(payload.get("cmd"), dict) else {}
        throttle = float(cmd_obj.get("throttle") or 0.0)
        steer = float(cmd_obj.get("steer") or 0.0)
        brake = float(cmd_obj.get("brake") or 0.0)
        estop_active = bool(payload.get("estop"))

        with self._lock:
            if isinstance(seq, int):
                self._last_seq = seq

        if estop_active:
            LOGGER.warning("estop active -> forcing cmd_vel=0")

        linear, angular = self._converter.to_velocity(
            command_raw if isinstance(command_raw, str) else None,
            throttle=throttle,
            steer=steer,
            brake=brake,
            estop_active=estop_active,
        )
        LOGGER.info(
            "cmd from UI seq=%s command=%s throttle=%.3f steer=%.3f brake=%.3f -> linear=%.3f angular=%.3f",
            seq,
            command_raw,
            throttle,
            steer,
            brake,
            linear,
            angular,
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
