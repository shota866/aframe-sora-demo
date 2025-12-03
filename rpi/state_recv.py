#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bridge import CommandSubscriber

from dotenv import load_dotenv

LOGGER = logging.getLogger("state-recv")


def _parse_signaling_urls(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [value.strip() for value in raw.split(",") if value.strip()]


def _normalise_label(value: Optional[str], fallback: str) -> str:
    label = (value or "").strip()
    if not label:
        return fallback
    return label if label.startswith("#") else f"#{label}"


def _load_env(explicit: Optional[str] = None) -> Optional[Path]:
    """Load .env from common locations. Returns the path that was loaded."""
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())

    here = Path(__file__).resolve()
    repo_root = here.parents[1]
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Raspberry Pi ctrl receiver (Python)")
    parser.add_argument("--room", help="Override VITE_SORA_CHANNEL_ID")
    parser.add_argument("--dotenv", help="Explicit path to .env file")
    parser.add_argument("--metadata", help="Override SORA_METADATA JSON")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose Sora logging")
    parser.add_argument("--connect-timeout", type=float, default=10.0, help="Connection timeout (seconds)")
    parser.add_argument(
        "--transport",
        choices=["webrtc", "mqtt"],
        help="Transport strategy for ctrl input (default: webrtc)",
    )
    parser.add_argument("--mqtt-host", help="MQTT broker host (env: MQTT_HOST)")
    parser.add_argument("--mqtt-port", type=int, help="MQTT broker port (env: MQTT_PORT, default 1883)")
    parser.add_argument("--mqtt-ctrl-topic", help="MQTT ctrl topic (env: MQTT_CTRL_TOPIC, default aframe/ctrl)")
    parser.add_argument("--mqtt-username", help="MQTT username (env: MQTT_USERNAME)")
    parser.add_argument("--mqtt-password", help="MQTT password (env: MQTT_PASSWORD)")
    parser.add_argument("--mqtt-keepalive", type=int, help="MQTT keepalive seconds (env: MQTT_KEEPALIVE, default 60)")
    parser.add_argument(
        "--publish-cmd-vel",
        action="store_true",
        help="Publish last_ctrl commands to a ROS 2 cmd_vel topic",
    )
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel", help="ROS 2 topic name (default: /cmd_vel)")
    parser.add_argument(
        "--cmd-vel-node-name",
        default="smagv_cmd_vel_bridge",
        help="ROS 2 node name used for cmd_vel publishing",
    )
    parser.add_argument(
        "--max-linear-speed",
        type=float,
        default=0.3,
        help="Maximum linear speed in m/s for throttle=±1.0",
    )
    parser.add_argument(
        "--max-angular-speed",
        type=float,
        default=-0.3,
        help="Maximum angular speed in rad/s for steer=±1.0",
    )
    parser.add_argument(
        "--brake-threshold",
        type=float,
        default=0.1,
        help="Brake value above which cmd_vel output is forced to zero",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=0.5,
        help="Seconds before cmd_vel output falls back to zero if no new command arrives",
    )
    return parser


def _load_metadata(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SORA_METADATA is invalid JSON: {exc}") from exc


def _resolve_transport_choice(raw_choice: Optional[str]) -> str:
    choice = (raw_choice or os.getenv("CONTROL_TRANSPORT") or "webrtc").lower()
    if choice not in {"webrtc", "mqtt"}:
        raise ValueError(f"Unsupported transport: {choice}")
    return choice


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    loaded_env = _load_env(args.dotenv)
    if loaded_env:
        LOGGER.info("loaded environment from %s", loaded_env)

    try:
        transport_choice = _resolve_transport_choice(args.transport)
    except ValueError as exc:
        parser.error(str(exc))
        return 1

    metadata_raw = args.metadata or os.getenv("SORA_METADATA")
    try:
        metadata = _load_metadata(metadata_raw)
    except ValueError as exc:
        parser.error(str(exc))
        return 1

    cmd_vel_publisher = None
    cmd_vel_subscriber: Optional["CommandSubscriber"] = None
    if args.publish_cmd_vel:
        try:
            try:
                from .bridge import CommandConverter, CmdVelPublisher, CommandSubscriber
            except ImportError:
                from bridge import CommandConverter, CmdVelPublisher, CommandSubscriber  # type: ignore[assignment]
        except ImportError as exc:  # pragma: no cover - import happens at runtime only
            parser.error(f"bridge modules unavailable: {exc}")

        try:
            converter = CommandConverter(
                max_linear_speed=args.max_linear_speed,
                max_angular_speed=args.max_angular_speed,
                brake_threshold=args.brake_threshold,
            )
            cmd_vel_publisher = CmdVelPublisher(
                node_name=args.cmd_vel_node_name,
                topic=args.cmd_vel_topic,
            )
            cmd_vel_publisher.start()
            cmd_vel_subscriber = CommandSubscriber(
                cmd_vel_publisher,
                converter,
                command_timeout_sec=args.command_timeout,
            )
            LOGGER.info(
                "cmd_vel bridge enabled: topic=%s linear<=%.2f angular<=%.2f timeout=%.2fs",
                args.cmd_vel_topic,
                args.max_linear_speed,
                args.max_angular_speed,
                args.command_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("could not initialize cmd_vel bridge: %s", exc)
            return 1

    transport = None
    if transport_choice == "mqtt":
        try:
            try:
                from .transport.mqtt_server import MQTTServerTransport
            except ImportError:
                from transport.mqtt_server import MQTTServerTransport  # type: ignore[assignment]
        except ImportError as exc:
            parser.error(f"MQTT transport unavailable: {exc}")

        host = args.mqtt_host or os.getenv("MQTT_HOST")
        if not host:
            parser.error("MQTT_HOST is required when transport=mqtt")

        port_raw = args.mqtt_port or os.getenv("MQTT_PORT") or 1883
        port = int(port_raw)
        ctrl_topic = args.mqtt_ctrl_topic or os.getenv("MQTT_CTRL_TOPIC") or "aframe/ctrl"
        username = args.mqtt_username or os.getenv("MQTT_USERNAME")
        password = args.mqtt_password or os.getenv("MQTT_PASSWORD")
        keepalive_raw = args.mqtt_keepalive or os.getenv("MQTT_KEEPALIVE") or 60
        keepalive = int(keepalive_raw)

        transport = MQTTServerTransport(
            broker_host=host,
            broker_port=port,
            ctrl_topic=ctrl_topic,
            username=username,
            password=password,
            keepalive=keepalive,
            connect_timeout=args.connect_timeout,
        )
    else:
        try:
            try:
                from .transport.webrtc_server import WebRTCServerTransport
            except ImportError:
                from transport.webrtc_server import WebRTCServerTransport  # type: ignore[assignment]
        except ImportError as exc:
            parser.error(f"WebRTC transport unavailable: {exc}")

        signaling_urls = _parse_signaling_urls(os.getenv("VITE_SORA_SIGNALING_URLS"))
        if not signaling_urls:
            parser.error("VITE_SORA_SIGNALING_URLS is required for WebRTC transport")

        channel_id = args.room or os.getenv("VITE_SORA_CHANNEL_ID") or "sora"
        ctrl_label = _normalise_label(os.getenv("VITE_CTRL_LABEL"), "#ctrl")

        transport = WebRTCServerTransport(
            signaling_urls=signaling_urls,
            channel_id=channel_id,
            ctrl_label=ctrl_label,
            metadata=metadata,
            debug=args.debug,
            connect_timeout=args.connect_timeout,
        )

    stop_event = threading.Event()

    def _handle_signal(signum: int, _frame) -> None:
        LOGGER.info("signal received: %s; shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    def _log_only_ctrl(payload: dict) -> None:
        LOGGER.info("ctrl payload received (no cmd_vel handler): %s", payload)

    transport.on_ctrl(cmd_vel_subscriber.process_ctrl_payload if cmd_vel_subscriber else _log_only_ctrl)

    try:
        transport.connect()
        LOGGER.info("ctrl transport started via %s", transport_choice)

        while not stop_event.wait(timeout=0.2):
            if transport.is_closed():
                LOGGER.info("transport reported closed; exiting")
                break
    except TimeoutError as exc:
        LOGGER.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("interrupted by user")
    finally:
        transport.close()
        if cmd_vel_subscriber is not None:
            cmd_vel_subscriber.close()
        if cmd_vel_publisher is not None:
            cmd_vel_publisher.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
