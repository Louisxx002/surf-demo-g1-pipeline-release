from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TurnShadowConfigTests(unittest.TestCase):
    def test_shadow_defaults_to_disabled_baseline_detector(self) -> None:
        result = subprocess.run(
            [
                "bash",
                "-lc",
                "source config/default.env; "
                "printf '%s\\n%s\\n' \"$TURN_SHADOW_ENABLE\" \"$TURN_SHADOW_DETECTOR\"",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0", "baseline"])

    def test_project_config_defaults_to_disabled_baseline_detector(self) -> None:
        env = os.environ.copy()
        env.pop("TURN_SHADOW_ENABLE", None)
        env.pop("TURN_SHADOW_DETECTOR", None)
        result = subprocess.run(
            [
                "python3",
                "-c",
                "from project_config import CONFIG; "
                "print(int(CONFIG.turn_shadow_enable)); "
                "print(CONFIG.turn_shadow_detector)",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["0", "baseline"])

    def test_local_env_example_keeps_shadow_mode_disabled(self) -> None:
        example = (ROOT / "config" / "local.env.example").read_text(encoding="utf-8")

        self.assertIn('TURN_SHADOW_ENABLE="0"', example)
        self.assertIn('TURN_SHADOW_DETECTOR="baseline"', example)


if __name__ == "__main__":
    unittest.main()
