#!/usr/bin/env python3
"""Bridge ROS RealSense frames into Sora as a small thumbnail stream."""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Dict, List, Optional

import rclpy
from dotenv import load_dotenv

from . import (
    FrameConverter,
    FrameConverterConfig,
    RealSenseImageSubscriber,
    SoraVideoPublisher,
    VideoPublishConfig,
)

LOGGER = logging.getLogger("image-to-sora")


def _parse_urls(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [value.strip() for value in raw.split(",") if value.strip()]


def _load_metadata(inline_json: Optional[str], file_path: Optional[str]) -> Dict[str, object]:
    result: Dict[str, object] = {}
    if file_path:
        with open(file_path, "r", encoding="utf-8") as handle:
            result.update(json.load(handle))
    if inline_json:
        result.update(json.loads(inline_json))
    return result


def _attach_ui_slot(metadata: Dict[str, object], ui_slot: Optional[str]) -> Dict[str, object]:
    if not ui_slot:
        return metadata
    video_meta = metadata.get("video")
    if not isinstance(video_meta, dict):
        video_meta = {}
    video_meta.setdefault("ui_slot", ui_slot)
    metadata["video"] = video_meta
    return metadata


def _load_env_file(explicit: Optional[str] = None) -> Optional[Path]:
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())

    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    candidates.extend(
        [
            Path.cwd() / ".env",
            repo_root / ".env",
            repo_root / "ui" / ".env",
            here.parent / ".env",
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            load_dotenv(candidate)
            return candidate

    load_dotenv()
    return None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send RealSense frames to Sora as a UI thumbnail.")
    parser.add_argument("--topic", default="/camera/color/image_raw", help="Image topic to subscribe.")
    parser.add_argument(
        "--signaling-url",
        action="append",
        dest="signaling_urls",
        help="Sora signaling URL. Can be repeated. Defaults to SORA_SIGNALING_URLS env.",
    )
    parser.add_argument(
        "--channel",
        default=os.environ.get("SORA_CHANNEL_ID", "aframe-manager"),
        help="Sora channel ID. Defaults to SORA_CHANNEL_ID env or 'aframe-manager'.",
    )
    parser.add_argument("--metadata", help="Inline JSON metadata.")
    parser.add_argument("--metadata-file", help="Path to metadata JSON.")
    parser.add_argument("--ui-slot", default="top-right", help="UI placement hint for the Web UI.")
    parser.add_argument("--width", type=int, default=320, help="Output width.")
    parser.add_argument("--height", type=int, default=180, help="Output height.")
    parser.add_argument("--fps", type=int, default=15, help="Max frame rate to send to Sora.")
    parser.add_argument("--bitrate", type=int, default=800, help="Video bitrate (kbps).")
    parser.add_argument("--codec", default="H264", help="Preferred video codec.")
    parser.add_argument("--track-label", default="camera-thumb", help="Video track label used by the UI.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Connection timeout for Sora.")
    parser.add_argument(
        "--dotenv",
        help="Path to .env file. Defaults to auto-detection in repo root/rpi/ui directories.",
    )
    return parser


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def main(argv: Optional[List[str]] = None) -> int:
    _configure_logging()
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    _load_env_file(args.dotenv)

    env_urls = _parse_urls(os.environ.get("SORA_SIGNALING_URLS"))
    signaling_urls = args.signaling_urls or env_urls
    if not signaling_urls:
        parser.error(
            "No signaling URLs provided. Use --signaling-url, SORA_SIGNALING_URLS, or a .env file."
        )

    metadata = _attach_ui_slot(_load_metadata(args.metadata, args.metadata_file), args.ui_slot)

    video_cfg = VideoPublishConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        codec=args.codec,
        bit_rate=args.bitrate,
        track_label=args.track_label,
    )

    publisher = SoraVideoPublisher(
        signaling_urls=signaling_urls,
        channel_id=args.channel,
        metadata=metadata,
        video_config=video_cfg,
        connect_timeout=args.timeout,
    )

    converter = FrameConverter(FrameConverterConfig(width=args.width, height=args.height))

    def _shutdown_handler(signum, _frame):
        LOGGER.info("Signal %s received -> shutting down", signum)
        rclpy.shutdown()

    signal.signal(signal.SIGINT, _shutdown_handler)
    signal.signal(signal.SIGTERM, _shutdown_handler)

    rclpy.init(args=None)
    node = RealSenseImageSubscriber(
        topic=args.topic,
        frame_converter=converter,
        frame_handler=lambda frame, ts: publisher.push_frame(frame, timestamp_ns=ts),
    )

    try:
        publisher.connect()
        rclpy.spin(node)
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
    finally:
        node.destroy_node()
        publisher.close()
        rclpy.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
