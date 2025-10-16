from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path

from dotenv import load_dotenv

from .config import load_settings
from .services.conductor import Conductor
from .utils.logging import setup_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sora Data-Channel Manager")
    parser.add_argument("--room", help="Sora room ID (overrides VITE_SORA_CHANNEL_ID)")
    parser.add_argument("--password", help="Room password (injects into metadata)")
    parser.add_argument("--estop", action="store_true", help="Trigger immediate estop on start")
    parser.add_argument("--log-level", help="Logging level (default: INFO)")
    parser.add_argument("--dotenv", help="Explicit path to .env file")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    setup_logging(level=args.log_level or os.getenv("MANAGER_LOG_LEVEL", "INFO"))

    dotenv_path = args.dotenv
    if not dotenv_path:
        repo_root = Path(__file__).resolve().parents[1]
        candidate = repo_root / "ui" / ".env"
        dotenv_path = str(candidate)
    load_dotenv(dotenv_path)

    config = load_settings(args)
    conductor = Conductor(config)

    if getattr(args, "estop", False):
        conductor.trigger_estop()

    def _handle_signal(_sig, _frame) -> None:  # noqa: ANN001
        conductor.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    conductor.start()
    conductor.wait_forever()


if __name__ == "__main__":
    main()

