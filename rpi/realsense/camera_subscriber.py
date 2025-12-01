from __future__ import annotations

import time
from typing import Callable

import numpy as np
from rclpy.node import Node
from rclpy.qos import QoSPresetProfiles
from sensor_msgs.msg import Image

from .frame_converter import FrameConversionError, FrameConverter

FrameHandler = Callable[[np.ndarray, int], bool]


class RealSenseImageSubscriber(Node):
    """ROS2 node that subscribes to RealSense images and forwards frames."""

    def __init__(
        self,
        topic: str,
        frame_converter: FrameConverter,
        frame_handler: FrameHandler,
        *,
        node_name: str = "image_to_sora",
    ) -> None:
        super().__init__(node_name)
        self._converter = frame_converter
        self._handler = frame_handler
        self._drop_count = 0
        self._last_drop_log = 0.0

        self.create_subscription(
            Image,
            topic,
            self._on_image,
            QoSPresetProfiles.SENSOR_DATA.value,
        )
        self.get_logger().info(f"Subscribed to {topic}")


    def _on_image(self, msg: Image) -> None:
        try:
            frame, timestamp_ns = self._converter.convert(msg)
        except FrameConversionError:
            self.get_logger().warning("Dropping frame due to conversion error")
            return

        if not self._handler(frame, timestamp_ns):
            self._drop_count += 1
            now = time.monotonic()
            if now - self._last_drop_log > 5.0:
                self.get_logger().warning(
                    "Publisher backpressure: dropped frames"
                )
                self._last_drop_log = now
