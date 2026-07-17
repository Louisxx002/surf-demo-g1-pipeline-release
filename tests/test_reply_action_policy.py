import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reply_action_policy import is_explicit_action_request, resolve_reply_action


def candidate(
    label: str,
    action_id: int,
    *,
    score: float = 0.95,
    backend: str = "test",
    should_execute: bool = True,
) -> dict:
    return {
        "text": "",
        "label": label,
        "official_name": label,
        "action_id": action_id,
        "score": score,
        "backend": backend,
        "should_execute": should_execute,
        "reason": "test candidate",
    }


class ReplyActionPolicyTests(unittest.TestCase):
    def test_only_direct_motion_requests_enter_explicit_action_path(self):
        for text in (
            "和我握个手",
            "挥个手",
            "请做一个动作",
            "给我一个拥抱",
            "鼓掌",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_explicit_action_request(text))

        for text in (
            "介绍一下优秀专业",
            "学校很棒在哪里",
            "拒绝申请怎么办",
            "介绍一下挥手动作",
            "介绍一下 X 光检查",
            "抬手动作的原理是什么",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_explicit_action_request(text))

    def test_system_and_termination_contexts_never_move(self):
        deepseek = candidate("高位挥手", 26, backend="deepseek")

        for context_kind in ("wake_ack", "system_ack", "session_end", "error"):
            with self.subTest(context_kind=context_kind):
                result = resolve_reply_action(
                    reply="我在",
                    user_text="你好小浦",
                    deepseek_action=deepseek,
                    context_kind=context_kind,
                )

                self.assertEqual(result["label"], "无动作")
                self.assertEqual(result["backend"], "system_no_action")
                self.assertFalse(result["should_execute"])

    def test_explicit_still_request_overrides_high_confidence_action(self):
        result = resolve_reply_action(
            reply="西交利物浦大学位于苏州。",
            user_text="不要动，介绍一下学校",
            deepseek_action=candidate("高位挥手", 26, backend="deepseek"),
        )

        self.assertEqual(result["label"], "无动作")
        self.assertEqual(result["backend"], "explicit_no_action")
        self.assertFalse(result["should_execute"])

    def test_explicit_action_request_has_priority(self):
        result = resolve_reply_action(
            reply="好的。",
            user_text="和我握个手",
            explicit_action=candidate("握手", 27, backend="keyword"),
            deepseek_action=candidate("举右手", 23, backend="deepseek"),
        )

        self.assertEqual(result["label"], "握手")
        self.assertEqual(result["backend"], "keyword")

    def test_self_intro_greeting_and_welcome_force_high_wave(self):
        cases = (
            ("你是谁", "我是小浦，西交利物浦大学的校园智能语音助手。"),
            ("你好", "你好呀，很高兴见到你。"),
            ("欢迎新同学", "欢迎来到西交利物浦大学。"),
        )

        for user_text, reply in cases:
            with self.subTest(user_text=user_text):
                result = resolve_reply_action(
                    reply=reply,
                    user_text=user_text,
                    deepseek_action=candidate("握手", 27, backend="deepseek"),
                )

                self.assertEqual(result["label"], "高位挥手")
                self.assertEqual(result["action_id"], 26)
                self.assertEqual(result["backend"], "reply_self_intro")

    def test_valid_deepseek_action_wins_before_semantic_fallback(self):
        result = resolve_reply_action(
            reply="恭喜你取得好成绩。",
            user_text="我拿奖了",
            deepseek_action=candidate("鼓掌", 17, backend="deepseek"),
            semantic_action=candidate("举右手", 23, backend="reply_info"),
        )

        self.assertEqual(result["label"], "鼓掌")
        self.assertEqual(result["backend"], "deepseek")

    def test_invalid_deepseek_candidate_continues_to_semantic_action(self):
        semantic = candidate("拥抱", 19, backend="reply_comfort")

        for deepseek in (
            candidate("无动作", -1, backend="deepseek", should_execute=False),
            candidate("鼓掌", 17, score=0.2, backend="deepseek"),
            candidate("非法动作", 999, backend="deepseek"),
        ):
            with self.subTest(deepseek=deepseek):
                result = resolve_reply_action(
                    reply="没关系，我会陪着你。",
                    user_text="我有点难过",
                    deepseek_action=deepseek,
                    semantic_action=semantic,
                    threshold=0.8,
                )

                self.assertEqual(result["label"], "拥抱")
                self.assertEqual(result["backend"], "reply_comfort")

    def test_ordinary_reply_falls_back_to_right_hand_up(self):
        result = resolve_reply_action(
            reply="西交利物浦大学位于苏州工业园区。",
            user_text="介绍一下学校",
            deepseek_action=candidate(
                "无动作", -1, backend="deepseek", should_execute=False
            ),
        )

        self.assertEqual(result["label"], "举右手")
        self.assertEqual(result["action_id"], 23)
        self.assertEqual(result["backend"], "reply_info_fallback")

    def test_english_words_containing_hi_are_not_greetings(self):
        result = resolve_reply_action(
            reply="This programme is taught in English.",
            user_text="Can you explain this programme?",
            deepseek_action=candidate(
                "无动作", -1, backend="deepseek", should_execute=False
            ),
        )

        self.assertEqual(result["label"], "举右手")
        self.assertEqual(result["backend"], "reply_info_fallback")

    def test_disabled_policy_preserves_existing_candidates_without_new_fallbacks(self):
        no_action = candidate(
            "无动作", -1, backend="deepseek", should_execute=False
        )
        ordinary = resolve_reply_action(
            reply="西交利物浦大学位于苏州工业园区。",
            user_text="介绍一下学校",
            deepseek_action=no_action,
            frequent_reply_enabled=False,
        )
        intro = resolve_reply_action(
            reply="我是小浦。",
            user_text="你是谁",
            deepseek_action=no_action,
            frequent_reply_enabled=False,
        )
        existing = resolve_reply_action(
            reply="恭喜你。",
            user_text="我拿奖了",
            deepseek_action=candidate("鼓掌", 17, backend="deepseek"),
            frequent_reply_enabled=False,
        )

        self.assertEqual(ordinary["label"], "无动作")
        self.assertEqual(intro["label"], "无动作")
        self.assertEqual(existing["label"], "鼓掌")


if __name__ == "__main__":
    unittest.main()
