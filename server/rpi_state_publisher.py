from __future__ import annotations

import argparse
import json
import logging
import math
import os
import queue
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Mapping, Optional

from dotenv import load_dotenv

from .config import ServerConfig, load_settings
from .domain.constants import STATE_RATE_HZ
from .services.conductor import Conductor
from .utils.logging import setup_logging

LOGGER = logging.getLogger("manager.rpi")
DEFAULT_QUEUE_SIZE = 512


class RaspberryPiStatePublisher(Conductor):
    """Conductor variant that forwards manager state over #state for Raspberry Pi receivers."""

    def __init__(
        self,
        config: ServerConfig,
        *,
        rate_hz: Optional[float] = None,
        queue_max: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        super().__init__(config)
        self._state_rate_hz = rate_hz if rate_hz and rate_hz > 0 else STATE_RATE_HZ
        self._state_queue: queue.Queue[Mapping[str, object]] = queue.Queue(maxsize=max(1, queue_max))
        self._state_source: Optional[Callable[[], Optional[Mapping[str, object]]]] = None

    @property
    def state_rate_hz(self) -> float:
        return self._state_rate_hz

    def _log_state_send(self, payload: str, size: int) -> None:  # type: ignore[override]
        if LOGGER.isEnabledFor(logging.INFO):
            LOGGER.info(
                "forwarding state label=%s size=%d payload=%s",
                self.config.state_label,
                size,
                payload,
            )

    def start(self) -> None:  # type: ignore[override]
        self._stop_event.clear()
        self._reconnect_event.set()
        self._threads = [
            threading.Thread(target=self._connection_loop, name="sora-conn", daemon=True),
            threading.Thread(target=self._state_loop, name="state", daemon=True),
            threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True),
            threading.Thread(target=self._stat_loop, name="stats", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def set_state_source(
        self,
        source: Optional[Callable[[], Optional[Mapping[str, object]]]],
    ) -> None:
        """Provide a callback returning state dictionaries when the queue is empty."""
        self._state_source = source

    def publish_state(
        self,
        state: Mapping[str, object],
        *,
        block: bool = False,
        timeout: Optional[float] = None,
    ) -> bool:
        """Queue a state payload to be normalised and sent on the #state channel."""
        if not isinstance(state, Mapping):
            LOGGER.warning("drop state (not a mapping): %s", state)
            return False
        try:
            # Shallow copy to avoid accidental mutation by caller while pending.
            self._state_queue.put(dict(state), block=block, timeout=timeout)
            return True
        except queue.Full:
            LOGGER.warning("state queue full; dropping frame")
            return False

    def _state_loop(self) -> None:  # type: ignore[override]
        target_dt = 1.0 / self._state_rate_hz if self._state_rate_hz > 0 else 0.0
        while not self._stop_event.is_set():
            start = time.perf_counter()
            ready = self._connection_alive.is_set() and self._dc.is_ready(self.config.state_label)
            if ready:
                self._flush_pending_states()
            elapsed = time.perf_counter() - start
            if target_dt > 0:
                sleep_for = target_dt - elapsed
                if sleep_for > 0:
                    time.sleep(sleep_for)

    def _flush_pending_states(self) -> None:
        while True:
            state = self._consume_state()
            if state is None and self._state_source:
                state = self._invoke_state_source()
            if state is None:
                break
            payload = self._normalise_state(state)
            if payload is None:
                continue
            self._send_state(payload)

    def _consume_state(self) -> Optional[Mapping[str, object]]:
        try:
            item = self._state_queue.get_nowait()
        except queue.Empty:
            return None
        return item

    def _invoke_state_source(self) -> Optional[Mapping[str, object]]:
        if not self._state_source:
            return None
        try:
            return self._state_source()
        except Exception:  # noqa: BLE001
            LOGGER.exception("state source callback raised")
            return None

    def _normalise_state(self, raw: Mapping[str, object]) -> Optional[dict[str, object]]:
        msg_type_raw = raw.get("type")
        msg_type = msg_type_raw.lower() if isinstance(msg_type_raw, str) else None
        payload: dict[str, object] = dict(raw) if msg_type == "state" else {"type": "state"}

        if msg_type != "state":
            pose_raw = raw.get("pose")
            vel_raw = raw.get("vel")
            if not isinstance(pose_raw, Mapping):
                LOGGER.warning("state missing 'pose': %s", raw)
                return None
            pose = {
                "x": _as_float(pose_raw.get("x"), 0.0),
                "y": _as_float(pose_raw.get("z"), 0.0),
                "heading": _as_float(pose_raw.get("yaw"), 0.0),
            }
            vel = {
                "linear": _as_float(vel_raw.get("vx"), 0.0) if isinstance(vel_raw, Mapping) else 0.0,
                "angular": _as_float(vel_raw.get("wz"), 0.0) if isinstance(vel_raw, Mapping) else 0.0,
            }
            status_raw = raw.get("status")
            status = dict(status_raw) if isinstance(status_raw, Mapping) else {"ok": True, "msg": "ok"}
            payload.update(
                {
                    "pose": pose,
                    "velocity": vel,
                    "status": status,
                    "step": {"dt_sec": _as_float(raw.get("dt_sec"), 0.0)},
                }
            )

        payload["type"] = "state"

        if "seq" not in payload or not isinstance(payload["seq"], int):
            payload["seq"] = self._next_state_seq()

        now_ms = int(time.time() * 1000.0)
        if "sent_at_ms" not in payload:
            legacy_t = payload.pop("t", None)
            if isinstance(legacy_t, (int, float)):
                payload["sent_at_ms"] = int(legacy_t)
            else:
                payload["sent_at_ms"] = now_ms
        else:
            payload.pop("t", None)

        # Ensure mandatory sections follow the new schema.
        pose_payload = payload.get("pose")
        if not isinstance(pose_payload, Mapping):
            pose_payload = {}
            payload["pose"] = pose_payload
        pose_payload.setdefault("x", _as_float(payload.get("x"), 0.0))
        pose_payload.setdefault("y", _as_float(payload.get("y"), 0.0))
        if "heading" not in pose_payload:
            if "theta" in payload:
                pose_payload["heading"] = _as_float(payload["theta"], 0.0)
            elif isinstance(pose_payload.get("yaw"), (int, float)):
                pose_payload["heading"] = _as_float(pose_payload.get("yaw"), 0.0)
            else:
                pose_payload["heading"] = 0.0

        velocity_payload = payload.get("velocity")
        if not isinstance(velocity_payload, Mapping):
            velocity_payload = {}
            payload["velocity"] = velocity_payload

        vx_legacy = payload.get("vx")
        wz_legacy = payload.get("wz")
        if "linear" not in velocity_payload:
            if isinstance(vx_legacy, (int, float)):
                velocity_payload["linear"] = _as_float(vx_legacy, 0.0)
            else:
                legacy_vel = payload.get("vel")
                if isinstance(legacy_vel, Mapping) and "vx" in legacy_vel:
                    velocity_payload["linear"] = _as_float(legacy_vel["vx"], 0.0)
                else:
                    velocity_payload["linear"] = 0.0
        if "angular" not in velocity_payload:
            if isinstance(wz_legacy, (int, float)):
                velocity_payload["angular"] = _as_float(wz_legacy, 0.0)
            else:
                legacy_vel = payload.get("vel")
                if isinstance(legacy_vel, Mapping) and "wz" in legacy_vel:
                    velocity_payload["angular"] = _as_float(legacy_vel["wz"], 0.0)
                else:
                    velocity_payload["angular"] = 0.0

        step_payload = payload.get("step")
        if not isinstance(step_payload, Mapping):
            step_payload = {}
            payload["step"] = step_payload
        sim_raw = payload.get("sim")
        if "dt_sec" not in step_payload:
            if isinstance(step_payload.get("dt"), (int, float)):
                step_payload["dt_sec"] = _as_float(step_payload.get("dt"), 0.0)
            elif isinstance(sim_raw, Mapping) and "dt" in sim_raw:
                step_payload["dt_sec"] = _as_float(sim_raw["dt"], 0.0)
            else:
                step_payload["dt_sec"] = 0.0
        if "dt" in step_payload:
            step_payload.pop("dt")

        status_payload = payload.get("status")
        if isinstance(status_payload, Mapping):
            if "hb_age_ms" not in status_payload and "hb_age" in status_payload:
                status_payload["hb_age_ms"] = _as_float(status_payload.pop("hb_age"), 0.0) * 1000.0

        # Remove legacy duplicates to keep payload compact.
        for legacy_key in ("x", "y", "theta", "vx", "wz", "vel", "sim"):
            payload.pop(legacy_key, None)

        return payload


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forward manager state frames to Raspberry Pi receivers.")
    parser.add_argument("--room", help="Sora room ID (overrides VITE_SORA_CHANNEL_ID)")
    parser.add_argument("--password", help="Room password (injects into metadata)")
    parser.add_argument("--log-level", help="Logging level (default: INFO)")
    parser.add_argument("--dotenv", help="Explicit path to .env file")
    parser.add_argument("--rate", type=float, default=STATE_RATE_HZ, help="State send rate in Hz (default: manager rate)")
    parser.add_argument("--queue", type=int, default=DEFAULT_QUEUE_SIZE, help="Maximum buffered states (default: 512)")
    parser.add_argument("--stdin", action="store_true", help="Read newline-delimited JSON state payloads from stdin")
    parser.add_argument("--demo", action="store_true", help="Inject a demo circular trajectory when idle")
    return parser


def _demo_state_source(rate_hz: float) -> Callable[[], Mapping[str, object]]:
    angular_speed = 0.35  # rad/s
    radius = 2.5  # metres
    start = time.time()
    dt = 1.0 / rate_hz if rate_hz > 0 else 1.0 / STATE_RATE_HZ

    def _state() -> Mapping[str, object]:
        elapsed = time.time() - start
        angle = angular_speed * elapsed
        x = radius * math.cos(angle)
        z = radius * math.sin(angle)
        yaw = math.atan2(math.sin(angle), math.cos(angle))
        vx = radius * angular_speed
        return {
            "pose": {"x": x, "y": 0.0, "z": z, "yaw": yaw},
            "vel": {"vx": vx, "wz": angular_speed},
            "status": {"ok": True, "msg": "demo"},
            "sim": {"dt": dt},
        }

    return _state


def _start_stdin_reader(publisher: RaspberryPiStatePublisher) -> threading.Thread:
    def _run() -> None:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                LOGGER.warning("stdin parse error: %s (%s)", exc, text[:128])
                continue
            if not publisher.publish_state(payload, block=False):
                LOGGER.warning("stdin queue full; dropped frame")

    thread = threading.Thread(target=_run, name="stdin-state-reader", daemon=True)
    thread.start()
    return thread


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(level=args.log_level or os.getenv("MANAGER_LOG_LEVEL", "INFO"))

    dotenv_path = args.dotenv
    if not dotenv_path:
        repo_root = Path(__file__).resolve().parents[1]
        dotenv_path = str(repo_root / "ui" / ".env")
    load_dotenv(dotenv_path)

    config = load_settings(args)
    publisher = RaspberryPiStatePublisher(config, rate_hz=args.rate, queue_max=args.queue)

    if args.demo:
        publisher.set_state_source(_demo_state_source(publisher.state_rate_hz))
        LOGGER.info("demo state source enabled")

    stdin_thread = None
    if args.stdin:
        stdin_thread = _start_stdin_reader(publisher)
        LOGGER.info("stdin reader started for state payloads")

    publisher.start()

    def _handle_signal(_sig, _frame) -> None:  # noqa: ANN001
        LOGGER.info("signal received, stopping publisher")
        publisher.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        publisher.wait_forever()
    finally:
        publisher.stop()
        if stdin_thread:
            stdin_thread.join(timeout=1.0)


__all__ = ["RaspberryPiStatePublisher", "main"]


if __name__ == "__main__":
    main()
