import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FollowupPromptLanguageTests(unittest.TestCase):
    def test_followup_prompt_has_chinese_and_english_config(self):
        project_config = (ROOT / "project_config.py").read_text(encoding="utf-8")
        default_env = (ROOT / "config" / "default.env").read_text(encoding="utf-8")

        self.assertIn("followup_prompt_text_zh", project_config)
        self.assertIn("followup_prompt_text_en", project_config)
        self.assertIn("LLM_FOLLOWUP_PROMPT_TEXT_ZH", default_env)
        self.assertIn("LLM_FOLLOWUP_PROMPT_TEXT_EN", default_env)

    def test_reply_tts_builder_selects_followup_by_language_context(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")

        self.assertIn("def _looks_english", source)
        self.assertIn("def _followup_prompt_for_text", source)
        self.assertIn("def _build_reply_tts_text(self, reply: str, user_text: str = \"\")", source)
        self.assertIn("_build_reply_tts_text(reply, user_text=user_text)", source)

    def test_self_speech_guard_knows_english_followup_prompt(self):
        source = (ROOT / "llm_surf_context_node.py").read_text(encoding="utf-8")

        self.assertIn("CONFIG.followup_prompt_text_en", source)
        self.assertIn("anything else to ask", source)


if __name__ == "__main__":
    unittest.main()
