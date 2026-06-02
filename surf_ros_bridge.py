from __future__ import annotations

import json
import os
import socket

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String


class SurfRosBridge(Node):
    def __init__(self) -> None:
        super().__init__("surf_udp_ros_bridge")
        self._string_publishers: dict[str, object] = {}
        self._bool_publishers: dict[str, object] = {}
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        host = os.environ.get("SURF_BRIDGE_HOST", "127.0.0.1")
        port = int(os.environ.get("SURF_BRIDGE_PORT", "18765"))
        self._sock.bind((host, port))
        self._sock.setblocking(False)
        self.create_timer(0.02, self._poll)
        self.get_logger().info(f"SURF UDP ROS bridge listening on {host}:{port}")

    def _poll(self) -> None:
        while True:
            try:
                raw, _ = self._sock.recvfrom(65535)
            except BlockingIOError:
                return

            try:
                event = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                self.get_logger().warn(f"Ignoring invalid UDP event: {exc}")
                continue

            topic = str(event.get("topic", ""))
            msg_type = str(event.get("type", ""))
            data = event.get("data")
            if not topic:
                continue

            if msg_type == "bool":
                pub = self._bool_publishers.get(topic)
                if pub is None:
                    pub = self.create_publisher(Bool, topic, 10)
                    self._bool_publishers[topic] = pub
                pub.publish(Bool(data=bool(data)))
            else:
                pub = self._string_publishers.get(topic)
                if pub is None:
                    pub = self.create_publisher(String, topic, 10)
                    self._string_publishers[topic] = pub
                pub.publish(String(data=str(data)))

            self.get_logger().info(f"published {topic}: {data}")


def main() -> None:
    rclpy.init()
    node = SurfRosBridge()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
