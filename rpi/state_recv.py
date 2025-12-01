#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bridge import CommandSubscriber

from dotenv import load_dotenv
from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode

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

#状態を受信するためのクラス
class StateReceiver:
    """Simple #state data-channel receiver using the Sora Python SDK."""

    def __init__(
        self,
        signaling_urls: Iterable[str],
        channel_id: str,
        ctrl_label: str,
        state_label: str,
        *,
        metadata: Optional[dict] = None,
        debug: bool = False,
        connect_timeout: float = 10.0,
        cmd_vel_subscriber: Optional["CommandSubscriber"] = None,
    ) -> None:
        self.signaling_urls = list(signaling_urls)
        self.channel_id = channel_id
        self.ctrl_label = ctrl_label
        self.state_label = state_label
        self.metadata = metadata
        self.debug = debug
        self.connect_timeout = connect_timeout
        self._cmd_vel_subscriber = cmd_vel_subscriber

        self._sora = Sora()
        self._conn: Optional[SoraConnection] = None

        self._connected = threading.Event()
        self._closed = threading.Event()
        self._ctrl_ready = threading.Event()
        self._state_ready = threading.Event()
        self._lock = threading.Lock()

    # Soraに接続して状態受信を開始するメソッド
    def connect(self) -> None:
        if not self.signaling_urls:
            raise ValueError("signaling_urls must not be empty")

        LOGGER.info("connecting to Sora: urls=%s channel=%s", self.signaling_urls, self.channel_id)

        conn = self._sora.create_connection(
            signaling_urls=self.signaling_urls,
            role="sendrecv",
            channel_id=self.channel_id,
            metadata=self.metadata,
            audio=False,
            video=True,
            data_channel_signaling=True,
            data_channels=[
                {"label": self.ctrl_label, "direction": "sendonly", "ordered": True},
                {"label": self.state_label, "direction": "recvonly", "ordered": True},
            ],
        )

        conn.on_set_offer = self._on_set_offer
        conn.on_notify = self._on_notify
        conn.on_data_channel = self._on_data_channel
        conn.on_message = self._on_message
        conn.on_disconnect = self._on_disconnect

        with self._lock:
            self._conn = conn

        conn.connect()

        if not self._connected.wait(timeout=self.connect_timeout):
            raise TimeoutError("Sora connection timeout")
        LOGGER.info("Sora connected")

    def wait_forever(self) -> None:
        try:
            self._closed.wait()
        finally:
            self.disconnect()

    def disconnect(self) -> None:
        with self._lock:
            conn = self._conn
            self._conn = None
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                LOGGER.debug("disconnect raised", exc_info=True)

    # ------------------------------------------------------------------ Callbacks
    def _on_set_offer(self, raw: str) -> None:
        if self.debug:
            LOGGER.debug("set_offer: %s", raw)

    def _on_notify(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("notify: could not decode JSON: %s", raw)
            return

        event_type = data.get("event_type")
        if data.get("type") == "notify" and event_type == "connection.created":
            LOGGER.info("connection created: connection_id=%s", data.get("connection_id"))
            self._connected.set()
        elif self.debug:
            LOGGER.debug("notify: %s", data)

    def _on_data_channel(self, label: str) -> None:
        if label == self.state_label:
            LOGGER.info("state channel ready: %s", label)
            self._state_ready.set()
        elif label == self.ctrl_label:
            LOGGER.info("ctrl channel ready (unused): %s", label)
            self._ctrl_ready.set()
        else:
            LOGGER.info("datachannel event: %s", label)

    def _on_message(self, label: str, data: bytes) -> None:
        if label != self.state_label:
            return

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            LOGGER.warning("state message not utf-8; dropping")
            return

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            LOGGER.warning("state message invalid JSON; dropping: %s", text)
            return

        msg_type = str(payload.get("type") or payload.get("t") or "").lower()
        if msg_type == "hb":
            LOGGER.debug("heartbeat received")
            return
        if msg_type != "state":
            if self.debug:
                LOGGER.debug("ignoring non-state payload: %s", payload)
            return

        seq = payload.get("seq")
        sent_at_ms = payload.get("sent_at_ms")
        pose = payload.get("pose") or {}
        velocity = payload.get("velocity") or {}
        status = payload.get("status") or {}
        last_ctrl = payload.get("last_ctrl") or {}
        LOGGER.info(
            "state seq=%s sent_at_ms=%s pos=(%s,%s) heading=%s vel=(lin:%s,ang:%s) last_ctrl_seq=%s status=%s",
            seq,
            sent_at_ms,
            pose.get("x"),
            pose.get("y"),
            pose.get("heading"),
            velocity.get("linear"),
            velocity.get("angular"),
            last_ctrl.get("seq"),
            status,
        )

        if self._cmd_vel_subscriber is not None:
            try:
                self._cmd_vel_subscriber.process_payload(payload)
            except Exception:  # noqa: BLE001
                LOGGER.exception("failed to publish cmd_vel command")

        timeline = payload.get("timeline")
        if isinstance(timeline, dict):
            timeline["pi_recv"] = int(time.time() * 1000.0)
            seq_value = timeline.get("seq") or payload.get("seq")
            ui_sent = timeline.get("ui_sent")
            mgr_recv = timeline.get("mgr_recv")
            mgr_sent = timeline.get("mgr_sent")
            pi_recv = timeline.get("pi_recv")

            def _delta_ms(start, end) -> Optional[int]:
                if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                    return int(end - start)
                return None

            #各時刻
            relative_ui_mgr = _delta_ms(ui_sent, mgr_recv)
            relative_ui_mgr_sent = _delta_ms(ui_sent, mgr_sent)
            relative_ui_pi_recv = _delta_ms(ui_sent, pi_recv)
            manager_prcessing= _delta_ms(mgr_recv, mgr_sent)
            relative_mgr_rpirecv= _delta_ms(relative_ui_mgr_sent, relative_ui_pi_recv)

            deltas: list[str] = []
            if relative_ui_mgr is not None:
                deltas.append(f"ui_mrgrcv={relative_ui_mgr}ms")
            if relative_ui_mgr_sent is not None:
                deltas.append(f"ui_mgrsent={relative_ui_mgr_sent}ms")
            if relative_ui_pi_recv is not None:
                deltas.append(f"ui_pirecv={relative_ui_pi_recv}ms")
            if manager_prcessing is not None:
                deltas.append(f"mgr_proc={manager_prcessing}ms")
            if relative_mgr_rpirecv is not None:
                deltas.append(f"mgr_pirecv={relative_mgr_rpirecv}ms")
            # Keep raw timeline JSON for later analysis even if human-readable summary omits mgr→pi

            try:
                raw_json = json.dumps(timeline, separators=(",", ":"))
            except TypeError:
                raw_json = str(timeline)

            if deltas:
                LOGGER.info("TIMELINE seq=%s %s raw=%s", seq_value, " ".join(deltas), raw_json)
            else:
                LOGGER.info("TIMELINE %s", raw_json)

    def _on_disconnect(self, code: SoraSignalingErrorCode, msg: str) -> None:
        LOGGER.info("Sora disconnected: code=%s msg=%s", code, msg)
        self._closed.set()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Raspberry Pi state receiver (Python)")
    parser.add_argument("--room", help="Override VITE_SORA_CHANNEL_ID")
    parser.add_argument("--dotenv", help="Explicit path to .env file")
    parser.add_argument("--metadata", help="Override SORA_METADATA JSON")
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose Sora logging")
    parser.add_argument("--connect-timeout", type=float, default=10.0, help="Connection timeout (seconds)")
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


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()#構文解析器の作成
    args = parser.parse_args(argv)#引数の解析

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    loaded_env = _load_env(args.dotenv)
    if loaded_env:
        LOGGER.info("loaded environment from %s", loaded_env)

    signaling_urls = _parse_signaling_urls(os.getenv("VITE_SORA_SIGNALING_URLS"))
    if not signaling_urls:
        parser.error("VITE_SORA_SIGNALING_URLS is required")

    channel_id = args.room or os.getenv("VITE_SORA_CHANNEL_ID") or "sora"
    ctrl_label = _normalise_label(os.getenv("VITE_CTRL_LABEL"), "#ctrl")
    state_label = _normalise_label(os.getenv("VITE_STATE_LABEL"), "#state")

    metadata_raw = args.metadata or os.getenv("SORA_METADATA")
    metadata = None
    if metadata_raw:
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError as exc:
            parser.error(f"SORA_METADATA is invalid JSON: {exc}")

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

    receiver = StateReceiver(
        signaling_urls=signaling_urls,
        channel_id=channel_id,
        ctrl_label=ctrl_label,
        state_label=state_label,
        metadata=metadata,
        debug=args.debug,
        connect_timeout=args.connect_timeout,
        cmd_vel_subscriber=cmd_vel_subscriber,
    )

    def _handle_signal(signum: int, _frame) -> None:
        LOGGER.info("signal received: %s; shutting down", signum)
        receiver.disconnect()
        receiver._closed.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        receiver.connect()
        receiver.wait_forever()
    except TimeoutError as exc:
        LOGGER.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("interrupted by user")
    finally:
        receiver.disconnect()
        if cmd_vel_subscriber is not None:
            cmd_vel_subscriber.close()
        if cmd_vel_publisher is not None:
            cmd_vel_publisher.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
