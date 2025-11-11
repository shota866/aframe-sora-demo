from __future__ import annotations

import logging
import threading

try:  # Optional ROS 2 dependency
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.executors import SingleThreadedExecutor
except ImportError:  # pragma: no cover
    rclpy = None  # type: ignore[assignment]
    Twist = None  # type: ignore[assignment]
    SingleThreadedExecutor = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)


class CmdVelPublisher:
    """Publish Twist messages to a ROS 2 cmd_vel topic."""

    def __init__(self, *, node_name: str, topic: str) -> None:
        if rclpy is None or Twist is None or SingleThreadedExecutor is None:
            raise RuntimeError("rclpy and geometry_msgs must be installed to publish cmd_vel")

        self._node_name = node_name
        self._topic = topic

        self._node = None
        self._publisher = None
        self._executor: Optional[SingleThreadedExecutor] = None
        self._spin_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._node is not None:
                return

            rclpy.init(args=None)
            self._node = rclpy.create_node(self._node_name)
            self._publisher = self._node.create_publisher(Twist, self._topic, 10)

            self._executor = SingleThreadedExecutor()
            self._executor.add_node(self._node)
            self._spin_thread = threading.Thread(target=self._executor.spin, daemon=True)
            self._spin_thread.start()
            LOGGER.info("cmd_vel publisher ready: node=%s topic=%s", self._node_name, self._topic)

    def publish(self, linear: float, angular: float) -> None:
        with self._lock:
            if self._publisher is None:
                return

            msg = Twist()
            msg.linear.x = linear
            msg.linear.y = 0.0
            msg.linear.z = 0.0
            msg.angular.x = 0.0
            msg.angular.y = 0.0
            msg.angular.z = angular

            self._publisher.publish(msg)

    def publish_zero(self) -> None:
        self.publish(0.0, 0.0)

    def stop(self) -> None:
        with self._lock:
            node = self._node
            executor = self._executor
            spin_thread = self._spin_thread
            publisher = self._publisher

            self._node = None
            self._executor = None
            self._spin_thread = None
            self._publisher = None

        if executor is not None and node is not None:
            executor.remove_node(node)

        if executor is not None:
            executor.shutdown()

        if node is not None and publisher is not None:
            node.destroy_publisher(publisher)

        if node is not None:
            node.destroy_node()

        if spin_thread is not None:
            spin_thread.join(timeout=1.0)

        if rclpy is not None and rclpy.is_initialized():
            rclpy.shutdown()
