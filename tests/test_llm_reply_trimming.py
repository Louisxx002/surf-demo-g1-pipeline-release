import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class LlmReplyTrimmingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["LLM_REPLY_BRIEF_ENABLE"] = "1"
        os.environ["LLM_REPLY_MAX_CHINESE_CHARS"] = "20"
        sys.modules.pop("project_config", None)
        sys.modules.pop("llm_server", None)
        cls.llm_server = importlib.import_module("llm_server")

    def test_brief_trim_does_not_cut_in_the_middle_of_a_sentence(self):
        reply = "西交利物浦大学在苏州，是西安交大和英国利物浦大学合办的中外合作大学，全英文授课，毕业拿双学位。"

        trimmed = self.llm_server._trim_reply_for_brief_mode(reply, "介绍一下西交利物浦大学")

        self.assertEqual(trimmed, reply)

    def test_brief_trim_keeps_complete_sentence_when_boundary_exists(self):
        reply = "西交利物浦大学在苏州。它是中外合作大学，全英文授课，毕业拿双学位。"

        trimmed = self.llm_server._trim_reply_for_brief_mode(reply, "介绍一下西交利物浦大学")

        self.assertEqual(trimmed, "西交利物浦大学在苏州。")

    def test_brief_trim_does_not_leave_only_an_english_acknowledgement(self):
        reply = (
            "Sure! "
            "The Information and Computing Science programme covers programming, "
            "algorithms, databases, artificial intelligence, and software engineering."
        )

        trimmed = self.llm_server._trim_reply_for_brief_mode(
            reply,
            "tell me about the modules in ICS",
        )

        self.assertNotEqual(trimmed, "Sure!")
        self.assertIn("Information and Computing Science", trimmed)


if __name__ == "__main__":
    unittest.main()
