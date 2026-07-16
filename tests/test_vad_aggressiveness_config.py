import importlib.util
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VOICE_CONFIG_PATH = ROOT / "deps" / "SURF2026_VoiceModule-main" / "config" / "voice_config.py"


def _load_voice_config(aggressiveness: str):
    previous = os.environ.get("VOICE_VAD_AGGRESSIVENESS")
    os.environ["VOICE_VAD_AGGRESSIVENESS"] = aggressiveness
    try:
        spec = importlib.util.spec_from_file_location("test_voice_config", VOICE_CONFIG_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module.VoiceConfig()
    finally:
        sys.modules.pop("test_voice_config", None)
        if previous is None:
            os.environ.pop("VOICE_VAD_AGGRESSIVENESS", None)
        else:
            os.environ["VOICE_VAD_AGGRESSIVENESS"] = previous


class VadAggressivenessConfigTests(unittest.TestCase):
    def test_voice_config_reads_vad_aggressiveness_from_environment(self):
        self.assertEqual(_load_voice_config("3").vad_aggressiveness, 3)

    def test_voice_runtime_passes_configured_aggressiveness_to_vad(self):
        source = (ROOT / "surf_voice_runtime.py").read_text(encoding="utf-8")
        self.assertIn("self._vad = VADEngine(CONFIG.vad_aggressiveness)", source)


if __name__ == "__main__":
    unittest.main()
