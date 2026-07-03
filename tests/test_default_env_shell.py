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


if __name__ == "__main__":
    unittest.main()
