from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import patch
import sys
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import rclpy  # noqa: F401
except ImportError:
    rclpy_stub = ModuleType("rclpy")
    rclpy_node_stub = ModuleType("rclpy.node")
    rclpy_executors_stub = ModuleType("rclpy.executors")
    rclpy_node_stub.Node = type("Node", (), {})
    rclpy_executors_stub.ExternalShutdownException = type(
        "ExternalShutdownException", (Exception,), {}
    )
    rclpy_stub.node = rclpy_node_stub
    sys.modules["rclpy"] = rclpy_stub
    sys.modules["rclpy.node"] = rclpy_node_stub
    sys.modules["rclpy.executors"] = rclpy_executors_stub

    std_msgs_stub = ModuleType("std_msgs")
    std_msgs_msg_stub = ModuleType("std_msgs.msg")
    std_msgs_msg_stub.Bool = type("Bool", (), {})
    std_msgs_msg_stub.String = type("String", (), {})
    std_msgs_stub.msg = std_msgs_msg_stub
    sys.modules["std_msgs"] = std_msgs_stub
    sys.modules["std_msgs.msg"] = std_msgs_msg_stub

import llm_surf_context_node as context_module


def write_valid_wav(path):
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 160)


def test_wake_ack_reuses_cached_wav_without_requesting_tts(tmp_path):
    cached = tmp_path / "wake_ack_cache.wav"
    write_valid_wav(cached)
    target = tmp_path / "tts.wav"

    class FakeNode:
        _wake_ack_cache_path = context_module.LlmSurfContextNode._wake_ack_cache_path
        _wake_ack_cache_valid = staticmethod(
            context_module.LlmSurfContextNode._wake_ack_cache_valid
        )
        _publish_cached_wake_ack = context_module.LlmSurfContextNode._publish_cached_wake_ack

        def __init__(self):
            self._tts_lock = context_module.threading.Lock()
            self.request_count = 0
            self.status = {"latency": {}}
            self._session_id = "test-session"

        def _write_tts_play_context(self, *args, **kwargs):
            return None

        def _request_tts_mp3(self, text, output_path=None):
            self.request_count += 1

        def _run_wake_ack_action(self):
            return None

        def _update_status(self, **kwargs):
            return None

        def _session_record(self, *args, **kwargs):
            return None

        def get_logger(self):
            return SimpleNamespace(info=lambda *_: None, warn=lambda *_: None)

        @staticmethod
        def _elapsed_ms(started_at, ended_at):
            return int((ended_at - started_at) * 1000)

    config = SimpleNamespace(
        runtime_dir=tmp_path,
        tts_wav_path=target,
    )
    node = FakeNode()

    with patch.object(context_module, "CONFIG", config):
        with patch.object(node, "_wake_ack_cache_path", return_value=cached):
            context_module.LlmSurfContextNode._play_wake_ack(node, "我在")

    assert target.read_bytes() == cached.read_bytes()
    assert node.request_count == 0


def test_wake_ack_cache_rejects_truncated_file(tmp_path):
    cached = tmp_path / "wake_ack_cache.wav"
    cached.write_bytes(b"not-a-wave")

    assert not context_module.LlmSurfContextNode._wake_ack_cache_valid(cached)
