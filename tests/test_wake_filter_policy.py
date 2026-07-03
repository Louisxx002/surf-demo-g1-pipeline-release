import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WakeFilterPolicyTests(unittest.TestCase):
    def test_wake_timeout_does_not_hard_drop_first_turn_asr(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")

        self.assertNotIn("Second LLM wake filter did not match; ignoring ASR text.", source)
        self.assertIn("wake listen window inactive; accepting first-turn ASR text", source)
        self.assertIn("CONFIG.first_turn_strict_gate_enable and not self._conversation_session_id", source)


if __name__ == "__main__":
    unittest.main()
