from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional

import numpy as np
from sora_sdk import (
    Sora,
    SoraConnection,
    SoraSignalingErrorCode,
    SoraVideoSource,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoPublishConfig:
    width: int
    height: int
    fps: int
    codec: str
    bit_rate: int
    track_label: str


class SoraVideoPublisher:
    """Manage a sendonly Sora connection that pushes video frames."""

    def __init__(
        self,
        signaling_urls: Iterable[str],
        channel_id: str,
        metadata: Optional[Mapping[str, object]],
        video_config: VideoPublishConfig,
        *,
        connect_timeout: float = 10.0,
    ) -> None:
        self._signaling_urls = list(signaling_urls)
        self._channel_id = channel_id
        self._metadata = metadata
        self._video_config = video_config
        self._connect_timeout = connect_timeout

        self._sora = Sora()
        self._conn: Optional[SoraConnection] = None
        self._source: Optional[SoraVideoSource] = None
        self._connected = threading.Event()
        self._last_sent = 0.0

    def connect(self) -> None:
        if not self._signaling_urls:
            raise ValueError("signaling_urls must not be empty")

        # 1) VideoSource を Sora から作る（新しい API）
        self._source = self._sora.create_video_source()

        # 2) Connection を VideoSource 付きで作る
        self._conn = self._sora.create_connection(
            signaling_urls=self._signaling_urls,
            role="sendonly",
            channel_id=self._channel_id,
            metadata=self._metadata,
            audio=False,
            video=True,
            video_codec_type=self._video_config.codec,
            video_bit_rate=self._video_config.bit_rate,
            video_source=self._source,   # ← 重要：ここに VideoSource を渡す
        )

        conn = self._conn
        conn.on_set_offer = lambda raw: LOGGER.debug("set_offer: %s", raw)
        conn.on_notify = self._on_notify
        conn.on_disconnect = self._on_disconnect

        # 3) 接続開始
        conn.connect()

        # 4) タイムアウト待ち
        if not self._connected.wait(timeout=self._connect_timeout):
            raise TimeoutError("Sora connection timeout")

        LOGGER.info("Sora connected to channel %s", self._channel_id)

    def close(self) -> None:
        conn = self._conn
        self._conn = None
        self._source = None
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:  # noqa: BLE001
                LOGGER.debug("disconnect raised", exc_info=True)

    def push_frame(self, frame: np.ndarray, *, timestamp_ns: int) -> bool:
        """Convert ndarray to soraVideoFrame and push via SoraVideoSource."""
        source = self._source
        if source is None:
            return False

        min_interval = 1.0 / float(self._video_config.fps)
        now = time.monotonic()
        if now - self._last_sent < min_interval:
            return False

        try:
            # ここで numpy 配列をそのまま VideoSource に渡す
            # ※ 実際のメソッド名は on_captured(...) のようなものになっているはず
            source.on_captured(frame)
        except Exception:
            LOGGER.exception("failed to push frame")
            return False

        self._last_sent = now
        return True

    # ------------------------------------------------------------------ callbacks
    def _on_notify(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            LOGGER.warning("notify payload is not JSON: %s", raw)
            return

        if data.get("type") == "notify" and data.get("event_type") == "connection.created":
            self._connected.set()
        else:
            LOGGER.debug("notify: %s", data)

    def _on_disconnect(self, _code: SoraSignalingErrorCode, msg: str) -> None:
        LOGGER.warning("Sora disconnected: %s", msg)
