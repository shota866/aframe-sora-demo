from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Dict, Optional

from ..domain.control import ControlSnapshot, SIMPLE_COMMAND_PRESETS, clamp
from ..domain.vehicle import VehicleModel
from .conductor_state import (
    ControlState,
    EstopState,
    HeartbeatState,
    StatsTracker,
)

LOGGER = logging.getLogger("manager")

# 受信したデータチャネルメッセージを処理するクラス
#メッセージ種別ごとのドメイン処理が一箇所で追える状態
class DataChannelMessageHandler:
    """Parse and dispatch data channel messages to domain components."""

    def __init__(
        self,
        ctrl_label: str,
        control_state: ControlState,
        heartbeat_state: HeartbeatState,
        estop_state: EstopState,
        vehicle: VehicleModel,
        vehicle_lock: threading.Lock,
        stats_tracker: StatsTracker,
    ) -> None:
        self._ctrl_label = ctrl_label
        self._control_state = control_state
        self._heartbeat_state = heartbeat_state
        self._estop_state = estop_state
        self._vehicle = vehicle
        self._vehicle_lock = vehicle_lock
        self._stats_tracker = stats_tracker

    # メッセージを処理するメソッド
    def handle(self, label: str, data: bytes) -> None:
        LOGGER.info("recv message label=%s payload=%s ", label, data[:128])
        try:
            payload = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("drop malformed json on %s: %s", label, data[:128])
            return
        msg_type = payload.get("t") or payload.get("type")
        msg_type_norm = msg_type.lower() if isinstance(msg_type, str) else None
        LOGGER.info("msg_type=%s label=%s", msg_type, label)
        if msg_type_norm in {"cmd", "ctrl"} and label == self._ctrl_label:
            self._handle_ctrl(payload)
        elif msg_type_norm == "hb":
            self._handle_heartbeat()
        elif msg_type_norm == "estop":
            self._handle_estop(payload)
        else:
            LOGGER.debug("ignore message type=%s label=%s expected_ctrl=%s", msg_type, label, self._ctrl_label)
            
    # コントロールメッセージを処理するメソッド
    def _handle_ctrl(self, msg: Dict[str, object]) -> None:
        seq = msg.get("seq")
        command = msg.get("command")

        if not isinstance(seq, int):
            LOGGER.warning("ctrl without seq or invalid seq type: %s", msg)
            return
        if isinstance(command, str):
            LOGGER.info("ctrl recv seq=%s command=%s", seq, command)
        else:
            LOGGER.info("ctrl recv seq=%s command=%s", seq, command)
        throttle = steer = brake = 0.0
        mode = "arcade"
        if isinstance(command, str):
            preset = SIMPLE_COMMAND_PRESETS.get(command.upper())#受け取った操作コマンドをSIMPLE_COMMAND_PRESETSに照らして、throttle（前進）,steer（操舵）,brakeの値に変換する
            
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
        client_ts_ms: Optional[float] = None
        for key in ("sent_at_ms", "ts", "t"):
            ts_candidate = msg.get(key)
            if isinstance(ts_candidate, (int, float)):
                client_ts_ms = float(ts_candidate)
                break

        now_wall = time.time()
        latency_ms = None
        if client_ts_ms is not None:
            latency_ms = now_wall * 1000.0 - client_ts_ms
        manager_recv_at_ms = int(now_wall * 1000.0)

        #コマンド情報をControlSnapshotに保存
        snapshot = ControlSnapshot(
            seq=seq,
            throttle=throttle,
            steer=steer,
            brake=brake,
            mode=mode,
            received_at=now_mono,
            client_timestamp_ms=int(client_ts_ms) if client_ts_ms is not None else None,
            manager_recv_at_ms=manager_recv_at_ms,
        )

        if not self._control_state.update_if_new(snapshot, latency_ms, now_wall):
            self._stats_tracker.inc_ctrl_drop()
            LOGGER.debug(
                "drop ctrl seq=%s (stale?). last_seq=%s",
                seq,
                self._control_state.get_last_ctrl().seq if self._control_state.get_last_ctrl() else None,
            )
            return

        self._stats_tracker.inc_ctrl_recv()
        if brake >= 0.99 and not math.isclose(throttle, 0.0, abs_tol=1e-3):
            LOGGER.debug("brake override detected, clearing throttle")

    def _handle_heartbeat(self) -> None:
        self._heartbeat_state.mark_from_ui(time.time())

    def _handle_estop(self, msg: Dict[str, object]) -> None:  # noqa: ARG002
        LOGGER.warning("estop requested via data channel: %s", msg)
        with self._vehicle_lock:
            self._vehicle.estop()
        self._estop_state.trigger()
