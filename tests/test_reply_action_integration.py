from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
import threading
import unittest
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
SOURCE = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")


def method_source(name: str, next_name: str) -> str:
    return SOURCE.split(f"def {name}", 1)[1].split(f"def {next_name}", 1)[0]


class ReplyActionIntegrationTests(unittest.TestCase):
    def test_stillness_modifier_does_not_become_robot_stop_skill(self):
        class FakeNode:
            _normalize_robot_skill_text = (
                context_module.LlmSurfContextNode._normalize_robot_skill_text
            )
            _is_direct_robot_stop_request = (
                context_module.LlmSurfContextNode._is_direct_robot_stop_request
            )

        with patch.object(
            context_module,
            "CONFIG",
            SimpleNamespace(robot_skill_enable=True),
        ):
            skill = context_module.LlmSurfContextNode._detect_robot_skill_command(
                FakeNode(),
                "不要动，介绍一下学校",
            )

        self.assertIsNone(skill)

    def test_direct_stop_request_remains_a_robot_skill(self):
        class FakeNode:
            _normalize_robot_skill_text = (
                context_module.LlmSurfContextNode._normalize_robot_skill_text
            )
            _is_direct_robot_stop_request = (
                context_module.LlmSurfContextNode._is_direct_robot_stop_request
            )

        with patch.object(
            context_module,
            "CONFIG",
            SimpleNamespace(robot_skill_enable=True),
        ):
            skill = context_module.LlmSurfContextNode._detect_robot_skill_command(
                FakeNode(),
                "小浦，请不要动",
            )

        self.assertEqual(skill["command"], "stop")

    def test_terminate_ack_queues_one_wave(self):
        calls = {"tts": [], "waves": []}

        class FakeLogger:
            def info(self, _message):
                return None

            def warn(self, _message):
                return None

        class FakeNode:
            _wake_state_lock = threading.Lock()
            _conversation_session_id = "session-1"
            _followup_until = 1.0
            _followup_generation = 0
            awaiting_command_after_wake = True
            _wake_listen_until = 1.0
            _wake_command_started = True

            def get_logger(self):
                return FakeLogger()

            def _update_status(self, **_kwargs):
                return None

            def _session_record(self, *_args, **_kwargs):
                return None

            def _write_followup_control_close(self, *_args):
                return None

            def _set_wake_light_blue(self):
                return None

            def _prepare_tts_wav(self, kind, text, session_id):
                calls["tts"].append((kind, text, session_id))
                return True

            def _queue_terminate_wave(self, text, session_id):
                calls["waves"].append((text, session_id))

        config = SimpleNamespace(
            terminate_ack_text="小浦退下了，有问题随时叫小浦。",
            terminate_ack_text_en="Xiaopu is standing by.",
        )
        with patch.object(context_module, "CONFIG", config):
            context_module.LlmSurfContextNode._handle_terminate_command(
                FakeNode(),
                "session-1",
                "退下吧",
            )

        self.assertEqual(len(calls["tts"]), 1)
        self.assertEqual(
            calls["waves"],
            [("小浦退下了，有问题随时叫小浦。", "session-1")],
        )

    def test_runtime_classifies_without_executing_then_executes_one_target(self):
        calls = {"classify": [], "execute": [], "log": []}

        class FakeNode:
            def _classification_from_deepseek_action(self, payload, reply):
                return payload

            def _run_action_classifier(self, text, backend):
                calls["classify"].append((text, backend))
                return {
                    "classification": {
                        "label": "鼓掌",
                        "action_id": 17,
                        "score": 0.95,
                        "backend": backend,
                    },
                    "execution": {"executed": True},
                }

            def _int_or_default(self, value, default):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default

            def _execute_classified_action(self, classification):
                calls["execute"].append(classification["action_id"])
                return {"executed": True, "reason": "test"}

            def _log_action_result(self, classification, execution, started_at, reply):
                calls["log"].append((classification["action_id"], execution["executed"]))

        config = SimpleNamespace(
            action_frequent_reply_enable=True,
            action_keyword_first=True,
            action_backend="deepseek",
            action_threshold=0.8,
        )
        with patch.object(context_module, "CONFIG", config):
            context_module.LlmSurfContextNode._run_reply_action_locked(
                FakeNode(),
                "西交利物浦大学位于苏州。",
                "介绍一下优秀专业",
                {"label": "无动作", "action_id": -1, "score": 0.0, "backend": "deepseek"},
            )

        self.assertEqual(calls["classify"], [("西交利物浦大学位于苏州。", "keyword")])
        self.assertEqual(calls["execute"], [17])
        self.assertEqual(calls["log"], [(17, True)])

    def test_disabled_switch_keeps_deepseek_priority_and_skips_classifiers(self):
        calls = {"classify": 0, "execute": []}

        class FakeNode:
            def _classification_from_deepseek_action(self, payload, reply):
                return payload

            def _run_action_classifier(self, text, backend):
                calls["classify"] += 1
                return None

            def _execute_classified_action(self, classification):
                calls["execute"].append(classification["action_id"])
                return {"executed": False, "reason": "test"}

            def _log_action_result(self, *args):
                return None

        config = SimpleNamespace(
            action_frequent_reply_enable=False,
            action_keyword_first=True,
            action_backend="deepseek",
            action_threshold=0.8,
        )
        with patch.object(context_module, "CONFIG", config):
            context_module.LlmSurfContextNode._run_reply_action_locked(
                FakeNode(),
                "好的。",
                "和我握个手",
                {"label": "鼓掌", "action_id": 17, "score": 0.95, "backend": "deepseek"},
            )

        self.assertEqual(calls["classify"], 0)
        self.assertEqual(calls["execute"], [17])

    def test_reply_action_uses_one_policy_decision_and_one_target_execution(self):
        section = method_source(
            "_run_reply_action_locked", "_classification_from_deepseek_action"
        )

        self.assertIn("resolve_reply_action(", section)
        self.assertEqual(section.count("_execute_classified_action("), 2)
        self.assertNotIn('payload.get("execution"', section)

    def test_classifier_path_never_receives_execute_flag(self):
        command_section = method_source("_action_command", "_run_action_classifier")
        classifier_section = method_source("_run_action_classifier", "_decode_json_payload")

        self.assertNotIn('command.append("--execute")', command_section)
        self.assertIn("self._action_command(reply, backend)", classifier_section)

    def test_action_logging_does_not_make_a_second_semantic_decision(self):
        section = method_source("_log_action_result", "_int_or_default")

        self.assertNotIn("_run_action_classifier", section)
        self.assertIn("action_auto_release", section)
        self.assertIn("action_release_after_sec", section)
        self.assertIn("arm_holding_release_required", section)

    def test_frequent_reply_switch_is_passed_to_policy(self):
        section = method_source(
            "_run_reply_action_locked", "_classification_from_deepseek_action"
        )

        self.assertIn("CONFIG.action_frequent_reply_enable", section)


if __name__ == "__main__":
    unittest.main()
