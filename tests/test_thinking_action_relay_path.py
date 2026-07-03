from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ThinkingActionRelayPathTests(unittest.TestCase):
    def test_thinking_action_uses_verified_action_runner(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")
        thinking_section = source.split("def _run_thinking_action_script", 1)[1].split(
            "@staticmethod", 1
        )[0]

        self.assertIn("CONFIG.action_runner", thinking_section)
        self.assertIn("CONFIG.thinking_action_id", thinking_section)
        self.assertIn("self.action_env()", thinking_section)
        self.assertNotIn("g1_arm7_sdk_dds_example.py", thinking_section)

    def test_pipeline_monitor_keeps_thinking_transition_disabled_by_default(self):
        source = (ROOT / "pipeline_monitor" / "server.py").read_text(encoding="utf-8")

        self.assertIn('"SURF_LLM_THINKING_ACK_ENABLE": "0"', source)
        self.assertIn('"SURF_LLM_THINKING_ACTION_ENABLE": "0"', source)
        self.assertIn('"LLM_THINKING_ACTION_ID": "25"', source)

    def test_project_config_keeps_thinking_transition_disabled_by_default(self):
        source = (ROOT / "project_config.py").read_text(encoding="utf-8")

        self.assertIn("thinking_ack_enable", source)
        self.assertIn(
            'thinking_ack_enable: bool = _env_bool_compat("SURF_LLM_THINKING_ACK_ENABLE", "SURF_QWEN_THINKING_ACK_ENABLE", False)',
            source,
        )
        self.assertIn("thinking_action_id", source)
        self.assertIn('LLM_THINKING_ACTION_ID"', source)


if __name__ == "__main__":
    unittest.main()
