import asyncio
import json
import os
import re
import sys
import time
from typing import Any

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String
except ImportError:
    print(
        "ROS2 Python dependencies are not available. "
        "Run this file inside a sourced ROS2 environment that provides rclpy and std_msgs.",
        file=sys.stderr,
    )
    raise

from chat_engine import chat
from memory_store import init_memory_db
from rag_config import settings
from vector_store import init_vector_db


WAKE_WORD = os.getenv("ROS_WAKE_WORD", "你好小浦")
AUDIO_TOPIC = os.getenv("ROS_AUDIO_TOPIC", "/audio_msg")
WAKE_TOPIC = os.getenv("ROS_WAKE_TOPIC", "/wake_word_event")
REPLY_TOPIC = os.getenv("ROS_REPLY_TOPIC", "/xjtlu_reply")
REPLY_FORMAT = os.getenv("ROS_REPLY_FORMAT", "text").lower()
ACK_TEXT = os.getenv("ROS_WAKE_ACK_TEXT", "我在")
SESSION_PREFIX = os.getenv("ROS_SESSION_PREFIX", "ros")


def normalize_text(text: str) -> str:
    return text.replace(" ", "").replace("\u3000", "").strip()


def safe_session_id(speaker: str) -> str:
    speaker = normalize_text(speaker) or "default"
    speaker = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "_", speaker)
    return f"{SESSION_PREFIX}-{speaker}"


def parse_audio_payload(raw: str) -> tuple[str, str]:
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return normalize_text(raw), "default"

    text = normalize_text(str(data.get("text", "")))
    speaker = str(data.get("speaker", "default")).strip() or "default"
    return text, speaker


class XjtluVoiceBridge(Node):
    def __init__(self) -> None:
        super().__init__("xjtlu_voice_bridge")
        init_vector_db(settings.rag_db)
        init_memory_db(settings.memory_db)

        self.reply_pub = self.create_publisher(String, REPLY_TOPIC, 10)
        self.create_subscription(String, WAKE_TOPIC, self.on_wake_word, 10)
        self.create_subscription(String, AUDIO_TOPIC, self.on_audio_msg, 10)
        self.last_ack_at = 0.0

        self.get_logger().info(
            f"listening: wake={WAKE_TOPIC}, audio={AUDIO_TOPIC}; publishing replies to {REPLY_TOPIC}"
        )

    def publish_reply(self, text: str, speaker: str = "default", event: str = "answer") -> None:
        msg = String()
        if REPLY_FORMAT == "json":
            msg.data = json.dumps(
                {"text": text, "speaker": speaker, "event": event},
                ensure_ascii=False,
            )
        else:
            msg.data = text
        self.reply_pub.publish(msg)
        self.get_logger().info(f"published {event}: {text}")

    def publish_ack(self, speaker: str = "default") -> None:
        now = time.monotonic()
        if now - self.last_ack_at < 1.0:
            return
        self.last_ack_at = now
        self.publish_reply(ACK_TEXT, speaker=speaker, event="wake_ack")

    def on_wake_word(self, msg: String) -> None:
        self.get_logger().info(f"wake word event received: {msg.data}")
        self.publish_ack()

    def on_audio_msg(self, msg: String) -> None:
        text, speaker = parse_audio_payload(msg.data)
        if not text:
            self.get_logger().warning("received empty audio_msg text")
            return

        if WAKE_WORD in text:
            self.publish_ack(speaker=speaker)
            text = text.replace(WAKE_WORD, "", 1).strip()
            if not text:
                return

        self.get_logger().info(f"audio command from {speaker}: {text}")
        try:
            result = asyncio.run(chat(safe_session_id(speaker), text))
        except Exception as exc:
            self.get_logger().error(f"failed to process audio command: {exc}")
            self.publish_reply("我这边处理语音指令时出错了，请稍后再试。", speaker=speaker, event="error")
            return

        answer = str(result.get("answer", "")).strip() or "我没有生成有效回答。"
        self.publish_reply(answer, speaker=speaker, event="answer")


def main() -> None:
    rclpy.init()
    node = XjtluVoiceBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
