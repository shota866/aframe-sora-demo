#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger("state-log-viewer")

DEFAULT_HISTORY = 10
DEFAULT_INTERVAL_SEC = 0.5


def _format_number(value: object, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "?"


def _format_state(payload: dict) -> str:
    pose = payload.get("pose") or {}
    vel = payload.get("vel") or {}
    status = payload.get("status") or {}

    timestamp = payload.get("t")
    if isinstance(timestamp, (int, float)):
        ts_text = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp / 1000.0))
    else:
        ts_text = "n/a"

    seq = payload.get("seq", "?")
    hb_age = status.get("hb_age")
    if isinstance(hb_age, (int, float)):
        hb_text = f"{hb_age:.1f}s"
    else:
        hb_text = status.get("hbAgeMs", "n/a")

    latency = status.get("ctrl_latency_ms")
    if isinstance(latency, (int, float)):
        latency_text = f"{latency:.1f}ms"
    else:
        latency_text = status.get("ctrlLatencyMs", "n/a")

    ok = status.get("ok", True)
    status_msg = status.get("msg", "ok" if ok else "warn")
    estop = " estop" if status.get("estop") else ""

    return (
        f"[{ts_text}] seq={seq} "
        f"x={_format_number(pose.get('x'))} "
        f"z={_format_number(pose.get('z'))} "
        f"yaw={_format_number(pose.get('yaw'))} "
        f"vx={_format_number(vel.get('vx'))} "
        f"wz={_format_number(vel.get('wz'))} "
        f"status={'ok' if ok else 'warn'}({status_msg}) "
        f"hb_age={hb_text} latency={latency_text}{estop}"
    )


class LogTailer:
    def __init__(self, log_path: Path, history: int, raw: bool, interval: float) -> None:
        self.log_path = log_path
        self.history = max(0, history)
        self.raw = raw
        self.interval = max(0.1, interval)
        self._running = True
        self._position = 0

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        LOGGER.info("watching log file %s", self.log_path)
        self._emit_history()
        self._tail_forever()

    def _emit_history(self) -> None:
        if self.history <= 0:
            return

        while self._running and not self.log_path.exists():
            LOGGER.info("waiting for log file %s ...", self.log_path)
            time.sleep(self.interval)

        if not self._running:
            return

        try:
            data = self.log_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            LOGGER.warning("could not read history: %s", exc)
            return

        lines = [line for line in data.splitlines() if line.strip()]
        for line in lines[-self.history :]:
            self._emit_line(line)

        self._position = self.log_path.stat().st_size

    def _tail_forever(self) -> None:
        remainder = ""
        while self._running:
            try:
                size = self.log_path.stat().st_size
            except FileNotFoundError:
                time.sleep(self.interval)
                continue
            except OSError as exc:
                LOGGER.warning("stat failed: %s", exc)
                time.sleep(self.interval)
                continue

            if size < self._position:
                LOGGER.info("log truncated; resetting position")
                self._position = 0
                remainder = ""

            if size > self._position:
                try:
                    with self.log_path.open("r", encoding="utf-8") as fh:
                        fh.seek(self._position)
                        chunk = fh.read(size - self._position)
                except OSError as exc:
                    LOGGER.warning("read failed: %s", exc)
                    time.sleep(self.interval)
                    continue

                self._position = size
                remainder += chunk
                *complete, remainder = remainder.splitlines()
                for line in complete:
                    if line:
                        self._emit_line(line)
            time.sleep(self.interval)

    def _emit_line(self, line: str) -> None:
        if self.raw:
            print(line)
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            LOGGER.warning("invalid JSON line: %s", line)
            return
        if not isinstance(payload, dict):
            LOGGER.warning("unexpected payload type: %s", type(payload))
            return
        print(_format_state(payload))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tail Sora state logs and print formatted output.")
    parser.add_argument(
        "-f",
        "--file",
        dest="file",
        help="Path to the state log file (default: env SORA_STATE_LOG_PATH or ./state.log)",
    )
    parser.add_argument(
        "-n",
        "--history",
        dest="history",
        type=int,
        default=DEFAULT_HISTORY,
        help=f"Number of historical entries to print on start (default: {DEFAULT_HISTORY}, 0 to skip)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON lines instead of formatted output",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SEC,
        help=f"Polling interval in seconds (default: {DEFAULT_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="logging level for viewer diagnostics (default: INFO)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    default_path = os.getenv("SORA_STATE_LOG_PATH", "state.log")
    log_path = Path(args.file or default_path).expanduser().resolve()

    tailer = LogTailer(log_path=log_path, history=args.history, raw=args.raw, interval=args.interval)

    def _handle_signal(signum: int, _frame) -> None:
        LOGGER.info("signal received: %s; stopping", signum)
        tailer.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        tailer.run()
    except KeyboardInterrupt:
        tailer.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
