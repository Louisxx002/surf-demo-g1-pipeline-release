import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DefaultEnvShellTests(unittest.TestCase):
    def test_default_env_can_be_sourced_by_bash(self):
        result = subprocess.run(
            ["bash", "-lc", "set -a; source config/default.env; set +a"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_default_env_has_natural_session_termination_commands(self):
        env = (ROOT / "config" / "default.env").read_text(encoding="utf-8")

        for phrase in ("再见", "拜拜", "我没有问题了", "你退下吧", "bye", "nothing else"):
            self.assertIn(phrase, env)
        self.assertIn("小浦退下了", env)

    def test_first_turn_mode_is_forwarded_to_llm_service_environment(self):
        script = (ROOT / "scripts" / "run_pipeline.sh").read_text(encoding="utf-8")
        match = re.search(r"^SYSTEMD_ENV=\(\n(?P<body>.*?)^\)", script, re.MULTILINE | re.DOTALL)

        self.assertIsNotNone(match)
        systemd_env = match.group("body")
        self.assertIn("--setenv=LLM_FIRST_TURN_MODE=", systemd_env)
        self.assertIn("--setenv=LLM_FIRST_TURN_COMPAT_LISTEN_SEC=", systemd_env)


if __name__ == "__main__":
    unittest.main()
