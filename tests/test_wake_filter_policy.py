import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WakeFilterPolicyTests(unittest.TestCase):
    def test_wake_timeout_does_not_hard_drop_first_turn_asr(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")

        self.assertNotIn("Second LLM wake filter did not match; ignoring ASR text.", source)
        self.assertIn("wake listen window inactive; accepting first-turn ASR text", source)
        self.assertIn("CONFIG.first_turn_strict_gate_enable and not self._conversation_session_id", source)

    def test_first_turn_strict_noise_gate_is_disabled_by_default(self):
        config_source = (ROOT / "project_config.py").read_text(encoding="utf-8")
        env_source = (ROOT / "config" / "default.env").read_text(encoding="utf-8")

        self.assertIn('first_turn_strict_gate_enable: bool = _env_bool("LLM_FIRST_TURN_STRICT_GATE_ENABLE", False)', config_source)
        self.assertIn('LLM_FIRST_TURN_STRICT_GATE_ENABLE="${LLM_FIRST_TURN_STRICT_GATE_ENABLE:-0}"', env_source)


if __name__ == "__main__":
    unittest.main()
