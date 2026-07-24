from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys
import threading
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


def write_valid_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 160)


class FakeNode:
    _thinking_ack_text = context_module.LlmSurfContextNode._thinking_ack_text
    _thinking_ack_cache_path = (
        context_module.LlmSurfContextNode._thinking_ack_cache_path
    )
    _thinking_ack_cache_valid = staticmethod(
        context_module.LlmSurfContextNode._thinking_ack_cache_valid
    )
    _publish_cached_thinking_ack = (
        context_module.LlmSurfContextNode._publish_cached_thinking_ack
    )
    _build_thinking_ack_cache = (
        context_module.LlmSurfContextNode._build_thinking_ack_cache
    )

    def __init__(self):
        self._tts_lock = threading.Lock()
        self._last_thinking_ack_text = ""
        self.records = []

    def _write_tts_play_context(self, *args, **kwargs):
        return None

    def _session_record(self, event, **kwargs):
        self.records.append((event, kwargs))

    def get_logger(self):
        return SimpleNamespace(info=lambda *_: None, warn=lambda *_: None)

    @staticmethod
    def _elapsed_ms(started_at, ended_at):
        return int((ended_at - started_at) * 1000)


def config_for(tmp_path: Path):
    return SimpleNamespace(
        runtime_dir=tmp_path,
        tts_wav_path=tmp_path / "tts.wav",
        thinking_ack_enable=True,
        thinking_ack_text="legacy",
        thinking_ack_texts_zh=("让我查一下。", "我来看看。", "让我想一想。"),
        thinking_ack_texts_en=("Let me check.", "Let me think.", "One moment."),
    )


def test_thinking_ack_selects_phrase_for_user_language(tmp_path):
    node = FakeNode()
    config = config_for(tmp_path)

    with patch.object(context_module, "CONFIG", config):
        chinese = node._thinking_ack_text("介绍一下西浦")
        english = node._thinking_ack_text("Tell me about XJTLU")

    assert chinese in config.thinking_ack_texts_zh
    assert english in config.thinking_ack_texts_en


def test_thinking_ack_avoids_immediate_repetition(tmp_path):
    node = FakeNode()
    config = config_for(tmp_path)

    with patch.object(context_module, "CONFIG", config):
        first = node._thinking_ack_text("介绍一下西浦")
        node._last_thinking_ack_text = first
        second = node._thinking_ack_text("介绍一下专业")

    assert second in config.thinking_ack_texts_zh
    assert second != first


def test_thinking_ack_reuses_cached_wav_without_network_tts(tmp_path):
    node = FakeNode()
    config = config_for(tmp_path)
    text = config.thinking_ack_texts_zh[0]
    cached = tmp_path / "thinking_ack.wav"
    write_valid_wav(cached)

    with patch.object(context_module, "CONFIG", config):
        with patch.object(node, "_thinking_ack_cache_path", return_value=cached):
            with patch.object(node, "_build_thinking_ack_cache") as build:
                played = context_module.LlmSurfContextNode._play_thinking_ack(
                    node, text, "session-1"
                )

    assert played
    assert config.tts_wav_path.read_bytes() == cached.read_bytes()
    build.assert_not_called()


def test_thinking_ack_cache_miss_skips_without_network_tts(tmp_path):
    node = FakeNode()
    config = config_for(tmp_path)
    missing = tmp_path / "missing.wav"

    with patch.object(context_module, "CONFIG", config):
        with patch.object(node, "_thinking_ack_cache_path", return_value=missing):
            with patch.object(node, "_build_thinking_ack_cache") as build:
                played = context_module.LlmSurfContextNode._play_thinking_ack(
                    node, "让我查一下。", "session-1"
                )

    assert not played
    assert node.records[-1][0] == "thinking_ack_cache_miss"
    build.assert_not_called()


def test_thinking_ack_prewarm_only_builds_missing_entries(tmp_path):
    node = FakeNode()
    config = config_for(tmp_path)
    valid_text = config.thinking_ack_texts_zh[0]
    valid_path = tmp_path / "valid.wav"
    write_valid_wav(valid_path)

    def cache_path(text):
        return valid_path if text == valid_text else tmp_path / f"{len(text)}-{text[0]}.wav"

    with patch.object(context_module, "CONFIG", config):
        with patch.object(node, "_thinking_ack_cache_path", side_effect=cache_path):
            with patch.object(node, "_build_thinking_ack_cache", return_value=True) as build:
                context_module.LlmSurfContextNode._prewarm_thinking_ack_cache(node)

    expected_missing = len(config.thinking_ack_texts_zh + config.thinking_ack_texts_en) - 1
    assert build.call_count == expected_missing
