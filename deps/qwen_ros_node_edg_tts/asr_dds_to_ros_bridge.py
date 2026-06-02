#!/usr/bin/env python3
"""Bridge Unitree G1 ASR DDS messages into the ROS2 /audio_msg topic.

This process is intentionally one-way:
  Unitree DDS rt/audio_msg -> ROS2 /audio_msg

It does not call robot APIs, does not play audio, and does not command motion.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String as RosString


PROJECT_ROOT = Path(__file__).resolve().parent
UNITREE_PYTHON = PROJECT_ROOT / "third_party" / "unitree_sdk2_python"
if str(UNITREE_PYTHON) not in sys.path:
    sys.path.insert(0, str(UNITREE_PYTHON))

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_ as UnitreeString


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge Unitree DDS rt/audio_msg ASR text to ROS2 /audio_msg."
    )
    parser.add_argument(
        "--network",
        default=os.environ.get("UNITREE_NETWORK_INTERFACE", "enp8s0"),
        help="Network interface connected to the robot, e.g. enp8s0.",
    )
    parser.add_argument(
        "--domain-id",
        type=int,
        default=int(os.environ.get("UNITREE_DOMAIN_ID", "0")),
        help="DDS domain id.",
    )
    parser.add_argument(
        "--dds-topic",
        default=os.environ.get("UNITREE_ASR_DDS_TOPIC", "rt/audio_msg"),
        help="Unitree DDS ASR topic.",
    )
    parser.add_argument(
        "--ros-topic",
        default=os.environ.get("QWEN_AUDIO_TOPIC", "/audio_msg"),
        help="ROS2 topic to publish.",
    )
    parser.add_argument(
        "--include-non-final",
        action="store_true",
        default=os.environ.get("ASR_BRIDGE_INCLUDE_NON_FINAL", "1") != "0",
        help="Forward non-final ASR messages. Enabled by default.",
    )
    parser.add_argument(
        "--dedup-window-sec",
        type=float,
        default=float(os.environ.get("ASR_BRIDGE_DEDUP_WINDOW_SEC", "2.0")),
        help="Ignore identical payloads seen recently to avoid self-loop repeats.",
    )
    return parser.parse_args()


def is_asr_text_payload(payload: str, include_non_final: bool) -> bool:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return bool(payload.strip())

    text = str(data.get("text", "")).strip()
    if not text:
        return False

    if not include_non_final and data.get("is_final") is False:
        return False

    return True


class AsrBridge(Node):
    def __init__(self, ros_topic: str, include_non_final: bool, dedup_window_sec: float):
        super().__init__("unitree_asr_dds_to_ros_bridge")
        self.publisher = self.create_publisher(RosString, ros_topic, 10)
        self.include_non_final = include_non_final
        self.dedup_window_sec = max(0.0, dedup_window_sec)
        self.recent: deque[tuple[float, str]] = deque(maxlen=128)
        self.ros_topic = ros_topic

    def _seen_recently(self, payload: str) -> bool:
        now = time.monotonic()
        while self.recent and now - self.recent[0][0] > self.dedup_window_sec:
            self.recent.popleft()
        if any(item == payload for _, item in self.recent):
            return True
        self.recent.append((now, payload))
        return False

    def handle_unitree_msg(self, msg: UnitreeString) -> None:
        payload = getattr(msg, "data", "")
        if not isinstance(payload, str):
            payload = str(payload)

        if not is_asr_text_payload(payload, self.include_non_final):
            self.get_logger().debug("Ignoring non-ASR payload: %s" % payload)
            return

        if self._seen_recently(payload):
            self.get_logger().debug("Ignoring duplicate ASR payload: %s" % payload)
            return

        ros_msg = RosString()
        ros_msg.data = payload
        self.publisher.publish(ros_msg)
        self.get_logger().info("Forwarded ASR to %s: %s" % (self.ros_topic, payload))


def main() -> None:
    args = parse_args()

    ChannelFactoryInitialize(args.domain_id, args.network)

    rclpy.init()
    bridge = AsrBridge(args.ros_topic, args.include_non_final, args.dedup_window_sec)
    subscriber = ChannelSubscriber(args.dds_topic, UnitreeString)
    subscriber.Init(bridge.handle_unitree_msg, 10)

    bridge.get_logger().info(
        "Unitree ASR bridge ready: %s -> %s on network=%s domain=%s"
        % (args.dds_topic, args.ros_topic, args.network, args.domain_id)
    )
    bridge.get_logger().info("This bridge only forwards ASR text; it does not command the robot.")

    try:
        rclpy.spin(bridge)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        subscriber.Close()
        bridge.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
