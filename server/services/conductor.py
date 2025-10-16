from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Dict, Optional

from sora_sdk import SoraConnection, SoraSignalingErrorCode

from ..adapters.dc_manager import DataChannelManager
from ..adapters.sora_base import create_sora_instance
from ..adapters.sora_connection import (
    SoraConnectionConfig,
    SoraEventHandlers,
    create_connection,
)
from ..config import ServerConfig
from ..domain.constants import (
    CTRL_DAMP_SEC,
    CTRL_HOLD_SEC,
    HEARTBEAT_IDLE_SEC,
    HEARTBEAT_SEC,
    IDLE_STATE_INTERVAL_SEC,
    PHYSICS_RATE_HZ,
    STATE_RATE_HZ,
)
from ..domain.control import (
    ControlSnapshot,
    SIMPLE_COMMAND_PRESETS,
    clamp,
)
from ..domain.vehicle import VehicleModel

LOGGER = logging.getLogger("manager")


class Conductor:
    """Coordinate domain logic with Sora transport."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self._sora = create_sora_instance()
        self._dc = DataChannelManager(config.ctrl_label, config.state_label)

        self._stop_event = threading.Event()
        self._reconnect_event = threading.Event()
        self._disconnected_event = threading.Event()
        self._connected_event = threading.Event()
        self._connection_alive = threading.Event()
        self._conn_lock = threading.Lock()
        self._conn: Optional[SoraConnection] = None
        self._connection_id: Optional[str] = None

        self._vehicle = VehicleModel()
        self._vehicle_lock = threading.Lock()
        self._state_seq = 0

        self._ctrl_lock = threading.Lock()
        self._last_ctrl: Optional[ControlSnapshot] = None
        self._last_ctrl_latency_ms: Optional[float] = None
        self._last_ctrl_recv_wall: Optional[float] = None

        self._last_hb_from_ui: Optional[float] = None
        self._last_hb_sent: float = time.time()
        self._estop_triggered: bool = False

        self._threads: list[threading.Thread] = []
        self._stats_lock = threading.Lock()
        self._ctrl_recv_count = 0
        self._ctrl_drop_count = 0
        self._state_sent_count = 0
        self._last_idle_state_emit: float = 0.0

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._stop_event.clear()
        self._reconnect_event.set()
        self._threads = [
            threading.Thread(target=self._connection_loop, name="sora-conn", daemon=True),
            threading.Thread(target=self._physics_loop, name="physics", daemon=True),
            threading.Thread(target=self._state_loop, name="state", daemon=True),
            threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True),
            threading.Thread(target=self._stat_loop, name="stats", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._connection_alive.clear()
        self._reconnect_event.set()
        self._disconnected_event.set()
        with self._conn_lock:
            conn = self._conn
            self._conn = None
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._dc.detach()
        for thread in self._threads:
            thread.join(timeout=1.0)

    def trigger_estop(self) -> None:
        LOGGER.warning("estop triggered locally")
        with self._vehicle_lock:
            self._vehicle.estop()
        self._estop_triggered = True

    def wait_forever(self) -> None:
        try:
            while not self._stop_event.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            LOGGER.info("interrupt received; stopping")
            self.stop()

    # ------------------------------------------------------------------ connection
    def _connection_loop(self) -> None:
        while not self._stop_event.is_set():
            self._reconnect_event.wait()
            if self._stop_event.is_set():
                break
            self._reconnect_event.clear()
            try:
                handlers = SoraEventHandlers(
                    on_set_offer=self._on_set_offer,
                    on_notify=self._on_notify,
                    on_data_channel=self._on_data_channel,
                    on_message=self._on_message,
                    on_disconnect=self._on_disconnect,
                )
                conn = create_connection(
                    self._sora,
                    SoraConnectionConfig(
                        signaling_urls=self.config.signaling_urls,
                        channel_id=self.config.channel_id,
                        ctrl_label=self.config.ctrl_label,
                        state_label=self.config.state_label,
                        metadata=self.config.metadata,
                    ),
                    handlers,
                )
                with self._conn_lock:
                    self._conn = conn
                self._dc.attach(conn)
                self._connection_id = None
                self._connected_event.clear()
                self._connection_alive.clear()
                self._disconnected_event.clear()

                LOGGER.info("connecting to Sora %s", self.config.signaling_urls)
                LOGGER.info("channel_id %s", self.config.channel_id)
                conn.connect()
                if not self._connected_event.wait(timeout=10.0):
                    LOGGER.error("Sora connect timeout")
                    conn.disconnect()
                    time.sleep(2.0)
                    self._reconnect_event.set()
                    continue

                self._connection_alive.set()
                LOGGER.info("Sora connected: connection_id=%s", self._connection_id)
                self._disconnected_event.wait()
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "connection loop error; signaling_urls=%s metadata=%s",
                    self.config.signaling_urls,
                    self.config.metadata,
                )
                time.sleep(2.0)
            finally:
                with self._conn_lock:
                    conn = self._conn
                    self._conn = None
                self._dc.detach()
                if conn is not None:
                    try:
                        conn.disconnect()
                    except Exception:  # noqa: BLE001
                        pass
                self._connection_alive.clear()
                if not self._stop_event.is_set():
                    time.sleep(1.0)
                    self._reconnect_event.set()

    # ------------------------------------------------------------------ event handlers
    def _on_set_offer(self, conn: SoraConnection, raw: str) -> None:
        with self._conn_lock:
            if conn is not self._conn:
                return
        msg = json.loads(raw)
        if msg.get("type") == "offer":
            self._connection_id = msg.get("connection_id")

    def _on_notify(self, conn: SoraConnection, raw: str) -> None:
        with self._conn_lock:
            if conn is not self._conn:
                return
        msg = json.loads(raw)
        if (
            msg.get("type") == "notify"
            and msg.get("event_type") == "connection.created"
            and msg.get("connection_id") == self._connection_id
        ):
            self._connected_event.set()

    def _on_data_channel(self, conn: SoraConnection, label: str) -> None:
        with self._conn_lock:
            if conn is not self._conn:
                return
        self._dc.mark_ready(label)
        LOGGER.info("data channel ready: %s", label)

    def _on_message(self, conn: SoraConnection, label: str, data: bytes) -> None:
        LOGGER.info("recv message label=%s payload=%s ", label, data[:128])
        with self._conn_lock:
            if conn is not self._conn:
                return
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("drop malformed json on %s", label)
            return
        msg_type = payload.get("t") or payload.get("type")
        msg_type_norm = msg_type.lower() if isinstance(msg_type, str) else None
        LOGGER.info("msg_type=%s label=%s ", msg_type, label)
        if msg_type_norm in {"cmd", "ctrl"} and label == self.config.ctrl_label:
            self._handle_ctrl(payload)
        elif msg_type_norm == "hb":
            self._handle_heartbeat(payload)
        elif msg_type_norm == "estop":
            self._handle_estop(payload)
        else:
            LOGGER.debug("ignore message type=%s label=%s", msg_type, label)

    def _on_disconnect(
        self,
        conn: SoraConnection,
        code: SoraSignalingErrorCode,
        msg: str,
    ) -> None:
        with self._conn_lock:
            if conn is not self._conn:
                return
        LOGGER.warning(
            "Sora disconnected: conn=%s code=%s msg=%s url_list=%s",
            conn,
            code,
            msg,
            self.config.signaling_urls,
        )
        self._connection_alive.clear()
        self._disconnected_event.set()

    # ------------------------------------------------------------------ message handling
    def _handle_ctrl(self, msg: Dict[str, object]) -> None:
        seq = msg.get("seq")
        command = msg.get("command")

        if not isinstance(seq, int):
            LOGGER.warning("ctrl without seq: %s", msg)
            return
        throttle = steer = brake = 0.0
        mode = "arcade"
        if isinstance(command, str):
            preset = SIMPLE_COMMAND_PRESETS.get(command.upper())
            if not preset:
                LOGGER.warning("unknown ctrl command=%s payload=%s", command, msg)
                return
            throttle = clamp(float(preset.get("throttle", 0.0)), -1.0, 1.0)
            steer = clamp(float(preset.get("steer", 0.0)), -1.0, 1.0)
            brake = clamp(float(preset.get("brake", 0.0)), 0.0, 1.0)
            if "mode" in preset:
                mode = str(preset["mode"])
        else:
            cmd = msg.get("cmd") or {}
            throttle = clamp(float(cmd.get("throttle", 0.0)), -1.0, 1.0)
            steer = clamp(float(cmd.get("steer", 0.0)), -1.0, 1.0)
            brake = clamp(float(cmd.get("brake", 0.0)), 0.0, 1.0)
            mode = str(cmd.get("mode", mode))

        now_mono = time.perf_counter()
        client_ts_ms = None
        for key in ("ts", "t"):
            ts_candidate = msg.get(key)
            if isinstance(ts_candidate, (int, float)):
                client_ts_ms = ts_candidate
                break

        with self._ctrl_lock:
            if self._last_ctrl and seq <= self._last_ctrl.seq:
                self._ctrl_drop_count += 1
                return
            self._last_ctrl = ControlSnapshot(
                seq=seq,
                throttle=throttle,
                steer=steer,
                brake=brake,
                mode=mode,
                received_at=now_mono,
                client_timestamp_ms=int(client_ts_ms) if client_ts_ms is not None else None,
            )
            self._ctrl_recv_count += 1
            self._last_ctrl_recv_wall = time.time()
            if client_ts_ms is not None:
                latency = time.time() * 1000.0 - float(client_ts_ms)
                self._last_ctrl_latency_ms = latency
        if brake >= 0.99 and not math.isclose(throttle, 0.0, abs_tol=1e-3):
            LOGGER.debug("brake override detected, clearing throttle")

    def _handle_heartbeat(self, msg: Dict[str, object]) -> None:  # noqa: ARG002
        self._last_hb_from_ui = time.time()

    def _handle_estop(self, msg: Dict[str, object]) -> None:  # noqa: ARG002
        LOGGER.warning("estop requested via data channel: %s", msg)
        with self._vehicle_lock:
            self._vehicle.estop()
        self._estop_triggered = True

    # ------------------------------------------------------------------ loops
    def _physics_loop(self) -> None:
        target_dt = 1.0 / PHYSICS_RATE_HZ
        last = time.perf_counter()
        while not self._stop_event.is_set():
            now = time.perf_counter()
            dt = now - last
            if dt <= 0.0:
                dt = target_dt
            last = now
            ctrl = None
            with self._ctrl_lock:
                if self._last_ctrl:
                    ctrl = self._last_ctrl
            with self._vehicle_lock:
                self._vehicle.step(ctrl, dt, now)
            elapsed = time.perf_counter() - now
            sleep_for = target_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def _state_loop(self) -> None:
        target_dt = 1.0 / STATE_RATE_HZ
        while not self._stop_event.is_set():
            start = time.perf_counter()
            if self._connection_alive.is_set() and self._dc.is_ready(self.config.state_label):
                payload = self._build_state_payload()
                if payload:
                    self._send_state(payload)
            elapsed = time.perf_counter() - start
            sleep_for = target_dt - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            with self._vehicle_lock:
                ctrl_age = self._vehicle.ctrl_age
            idle = math.isinf(ctrl_age) or ctrl_age > CTRL_HOLD_SEC + CTRL_DAMP_SEC
            interval = HEARTBEAT_IDLE_SEC if idle else HEARTBEAT_SEC
            if now - self._last_hb_sent >= interval:
                self._send_heartbeat()
                self._last_hb_sent = now
            time.sleep(0.1)

    def _stat_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(5.0)
            with self._stats_lock:
                ctrl_recv = self._ctrl_recv_count
                ctrl_drop = self._ctrl_drop_count
                state_sent = self._state_sent_count
            LOGGER.debug(
                "stats ctrl_recv=%s ctrl_drop=%s state_sent=%s",
                ctrl_recv,
                ctrl_drop,
                state_sent,
            )

    # ------------------------------------------------------------------ payload helpers
    def _build_state_payload(self) -> Dict[str, object]:
        with self._vehicle_lock:
            data = self._vehicle.snapshot()
            ctrl_age = self._vehicle.ctrl_age
            estop = self._vehicle.estop_active

        hb_age = None
        if self._last_hb_from_ui:
            hb_age = time.time() - self._last_hb_from_ui

        now_ms = int(time.time() * 1000.0)
        now_wall = time.time()
        status_ok = True
        status_msg = "ok"
        if hb_age is not None and hb_age > HEARTBEAT_IDLE_SEC:
            status_ok = False
            status_msg = f"hb age {hb_age:.1f}s"
        if ctrl_age > IDLE_STATE_INTERVAL_SEC:
            if now_wall - self._last_idle_state_emit < IDLE_STATE_INTERVAL_SEC:
                return {}
            self._last_idle_state_emit = now_wall
        else:
            self._last_idle_state_emit = now_wall

        if estop:
            status_ok = False
            status_msg = "estop"

        payload: Dict[str, object] = {
            "type": "state",
            "seq": self._next_state_seq(),
            "t": now_ms,
            "pose": data["pose"],
            "vel": data["vel"],
            "status": {"ok": status_ok, "msg": status_msg},
            "sim": data["sim"],
        }
        pose = data["pose"]
        vel = data["vel"]
        payload.update(
            {
                "x": pose.get("x"),
                "y": pose.get("z"),
                "theta": pose.get("yaw"),
                "vx": vel.get("vx"),
                "wz": vel.get("wz"),
            }
        )
        if hb_age is not None:
            payload["status"]["hb_age"] = hb_age
        if self._last_ctrl_latency_ms is not None:
            payload["status"]["ctrl_latency_ms"] = self._last_ctrl_latency_ms
        if self._estop_triggered:
            payload["status"]["estop"] = True
        return payload

    def _next_state_seq(self) -> int:
        self._state_seq = (self._state_seq + 1) % (1 << 31)
        return self._state_seq

    def _send_state(self, obj: Dict[str, object]) -> None:
        if not obj:
            return
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        with self._conn_lock:
            conn = self._conn
        if not conn:
            return
        try:
            conn.send_data_channel(self.config.state_label, data)
            with self._stats_lock:
                self._state_sent_count += 1
        except Exception as exc:  # noqa: BLE001
            LOGGER.debug(
                "send failed just before disconnect: label=%s err=%s",
                self.config.state_label,
                exc,
            )

    def _send_heartbeat(self) -> None:
        if not self._connection_alive.is_set():
            return
        payload = json.dumps(
            {
                "type": "hb",
                "role": "server",
                "t": int(time.time() * 1000.0),
                "label": self.config.state_label,
            }
        ).encode("utf-8")
        with self._conn_lock:
            conn = self._conn
        if not conn:
            return
        try:
            conn.send_data_channel(self.config.state_label, payload)
        except Exception:  # noqa: BLE001
            LOGGER.debug("heartbeat send failed")


__all__ = ["Conductor"]
