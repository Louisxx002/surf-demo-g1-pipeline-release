from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VOICE_TOOLS = REPO_ROOT / "deps" / "SURF2026_VoiceModule-main" / "tools"
sys.path.insert(0, str(VOICE_TOOLS))

from kws_keyword_tools import (  # noqa: E402
    candidate_xiaopu_keywords,
    parse_keyword_line,
    validate_keyword_lines,
)


class KwsKeywordToolsTest(unittest.TestCase):
    def test_parse_keyword_line_splits_tokens_and_label(self) -> None:
        parsed = parse_keyword_line("h ei x iǎo p ǔ @你好小浦")

        self.assertEqual(parsed.tokens, ("h", "ei", "x", "iǎo", "p", "ǔ"))
        self.assertEqual(parsed.label, "你好小浦")

    def test_validate_keyword_lines_reports_unknown_tokens(self) -> None:
        errors = validate_keyword_lines(
            ["h nope x iǎo p ǔ @你好小浦"],
            {"h", "x", "iǎo", "p", "ǔ"},
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("line 1", errors[0])
        self.assertIn("nope", errors[0])

    def test_candidate_xiaopu_keywords_include_chinese_and_hi_hey_variants(self) -> None:
        lines = candidate_xiaopu_keywords()

        self.assertIn("n ǐ h ǎo x iǎo p ǔ @你好小浦", lines)
        self.assertIn("h ǎi x iǎo p ǔ @你好小浦", lines)
        self.assertIn("h i x iǎo p ǔ @你好小浦", lines)
        self.assertIn("h ei x iǎo p ǔ @你好小浦", lines)
        self.assertEqual(len(lines), len(set(lines)))


if __name__ == "__main__":
    unittest.main()
