import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "xjtlu-rag-system"))

import chat_engine


class ReplyActionPromptPolicyTests(unittest.TestCase):
    def test_enabled_policy_prefers_safe_actions_for_normal_replies(self):
        rules = chat_engine._action_prompt_rules(True)

        self.assertIn("自我介绍、问候或欢迎", rules)
        self.assertIn("高位挥手", rules)
        self.assertIn("普通讲解", rules)
        self.assertIn("举右手", rules)
        self.assertIn("明确要求不动", rules)

    def test_disabled_policy_preserves_original_no_action_rule(self):
        rules = chat_engine._action_prompt_rules(False)

        self.assertIn("信息说明", rules)
        self.assertIn("选择“无动作”", rules)
        self.assertNotIn("普通讲解优先选择“举右手”", rules)

    def test_environment_switch_controls_prompt_policy(self):
        with patch.dict(os.environ, {"LLM_ACTION_FREQUENT_REPLY_ENABLE": "0"}):
            disabled = chat_engine._frequent_reply_action_enabled()
        with patch.dict(os.environ, {"LLM_ACTION_FREQUENT_REPLY_ENABLE": "1"}):
            enabled = chat_engine._frequent_reply_action_enabled()

        self.assertFalse(disabled)
        self.assertTrue(enabled)

    def test_default_env_and_project_config_define_same_switch(self):
        env = (ROOT / "config" / "default.env").read_text(encoding="utf-8")
        config = (ROOT / "project_config.py").read_text(encoding="utf-8")

        self.assertIn("LLM_ACTION_FREQUENT_REPLY_ENABLE", env)
        self.assertIn("action_frequent_reply_enable", config)


if __name__ == "__main__":
    unittest.main()
