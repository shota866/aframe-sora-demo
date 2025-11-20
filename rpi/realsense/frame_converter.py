from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np
from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image

LOGGER = logging.getLogger(__name__)


class FrameConversionError(RuntimeError):
    """Raised when ROS image frames cannot be converted."""


@dataclass(frozen=True)
class FrameConverterConfig:
    width: int
    height: int


class FrameConverter:
    """Convert ROS sensor_msgs/Image messages into resized BGR ndarrays."""

    def __init__(self, config: FrameConverterConfig) -> None:
        self._config = config
        self._bridge = CvBridge()

    @staticmethod
    def _stamp_to_ns(msg: Image) -> int:
        stamp = msg.header.stamp
        return stamp.sec * 1_000_000_000 + stamp.nanosec

    def convert(self, msg: Image) -> tuple[np.ndarray, int]:
        """Return (resized_bgr_frame, timestamp_ns)."""
        try:
            bgr = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:  # pragma: no cover - depends on runtime
            LOGGER.warning("cv_bridge failed: %s", exc)
            raise FrameConversionError(str(exc)) from exc

        resized = cv2.resize(
            bgr,
            (self._config.width, self._config.height),
            interpolation=cv2.INTER_AREA,
        )
        return resized, self._stamp_to_ns(msg)
