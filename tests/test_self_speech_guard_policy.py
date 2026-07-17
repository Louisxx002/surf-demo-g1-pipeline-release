import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import sys

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


ROOT = Path(__file__).resolve().parents[1]


class SelfSpeechGuardPolicyTests(unittest.TestCase):
    @staticmethod
    def _match_asr(tts_text, asr_text):
        class FakeNode:
            _normalize_asr_text = context_module.LlmSurfContextNode._normalize_asr_text

            def _read_tts_guard(self):
                return {
                    "active": True,
                    "kind": "reply",
                    "text": tts_text,
                    "updated_at": 1.0,
                    "guard_until": 9999999999.0,
                }

        config = SimpleNamespace(
            tts_guard_enable=True,
            followup_prompt_text="",
            followup_prompt_text_zh="还有什么想问的吗",
            followup_prompt_text_en="Anything else to ask?",
            self_speech_similarity_threshold=0.90,
        )
        with patch.object(context_module, "CONFIG", config):
            return context_module.LlmSurfContextNode._self_speech_asr_match(
                FakeNode(),
                asr_text,
            )

    def test_user_sentence_containing_wake_ack_is_not_rejected(self):
        matched, reason = self._match_asr("我在", "我在工作")

        self.assertFalse(matched, reason)

    def test_negative_answer_similar_to_followup_prompt_is_not_rejected(self):
        matched, reason = self._match_asr(
            "还有什么想问的吗",
            "没有什么想问的了",
        )

        self.assertFalse(matched, reason)

    def test_related_question_reusing_tts_phrase_is_not_rejected(self):
        matched, reason = self._match_asr(
            "利物浦大学是英国著名的红砖大学，也是罗素大学集团成员。",
            "什么是红砖大学啊",
        )

        self.assertFalse(matched, reason)

    def test_exact_wake_ack_is_still_rejected(self):
        matched, _ = self._match_asr("我在", "我在")

        self.assertTrue(matched)

    def test_exact_followup_prompt_is_still_rejected(self):
        matched, _ = self._match_asr("还有什么想问的吗", "还有什么想问的吗")

        self.assertTrue(matched)

    def test_related_followup_question_is_not_mistaken_for_tts_echo(self):
        tts_text = (
            "我是小浦，西交利物浦大学的校园智能语音助手。"
            "你说的西郊利物浦应该是西交利物浦吧？"
            "它是由西安交通大学和英国利物浦大学合作创办的中外合办大学，"
            "位于苏州工业园区，全英文教学，毕业生拿中英双学位。"
            "还有什么想问的吗？"
        )

        class FakeNode:
            _normalize_asr_text = context_module.LlmSurfContextNode._normalize_asr_text

            def _read_tts_guard(self):
                return {
                    "active": True,
                    "kind": "reply",
                    "text": tts_text,
                    "updated_at": 1.0,
                    "guard_until": 9999999999.0,
                }

        config = SimpleNamespace(
            tts_guard_enable=True,
            followup_prompt_text="",
            followup_prompt_text_zh="还有什么想问的吗",
            followup_prompt_text_en="Anything else to ask?",
            self_speech_similarity_threshold=0.90,
        )
        with patch.object(context_module, "CONFIG", config):
            matched, reason = context_module.LlmSurfContextNode._self_speech_asr_match(
                FakeNode(),
                "利物浦有什么好玩的吗",
            )

        self.assertFalse(matched, reason)

    def test_full_tts_echo_is_still_rejected(self):
        tts_text = "我是小浦，西交利物浦大学的校园智能语音助手。"

        class FakeNode:
            _normalize_asr_text = context_module.LlmSurfContextNode._normalize_asr_text

            def _read_tts_guard(self):
                return {
                    "active": True,
                    "kind": "reply",
                    "text": tts_text,
                    "updated_at": 1.0,
                    "guard_until": 9999999999.0,
                }

        config = SimpleNamespace(
            tts_guard_enable=True,
            followup_prompt_text="",
            followup_prompt_text_zh="还有什么想问的吗",
            followup_prompt_text_en="Anything else to ask?",
            self_speech_similarity_threshold=0.90,
        )
        with patch.object(context_module, "CONFIG", config):
            matched, _ = context_module.LlmSurfContextNode._self_speech_asr_match(
                FakeNode(),
                "我是小浦，西交利物浦大学的校园智能语音助手",
            )

        self.assertTrue(matched)

    def test_terminate_commands_are_checked_before_self_speech_guard(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")
        handler = source[
            source.index("def on_audio_msg") : source.index('self.get_logger().info(\n            "[ASR] ')
        ]

        self.assertLess(
            handler.index("terminate command matched before self-speech guard"),
            handler.index("self._self_speech_asr_match"),
        )

    def test_fuzzy_overlap_rules_are_not_present(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")

        self.assertNotIn("tts_coverage_echo", source)
        self.assertNotIn("tts_longest_match_echo", source)
        self.assertNotIn("tts_substring_echo", source)
        self.assertNotIn("tts_contains_echo", source)


if __name__ == "__main__":
    unittest.main()
