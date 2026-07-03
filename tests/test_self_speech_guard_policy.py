import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SelfSpeechGuardPolicyTests(unittest.TestCase):
    def test_char_coverage_echo_rule_is_limited_to_cjk_text(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")

        self.assertIn("def _contains_cjk", source)
        coverage_rule = source[source.index("and len(normalized_asr) >= 8") : source.index("return True, f\"tts_coverage_echo")]
        self.assertIn("self._contains_cjk(normalized_asr)", coverage_rule)


if __name__ == "__main__":
    unittest.main()
