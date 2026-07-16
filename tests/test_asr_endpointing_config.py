"""Regression tests for noisy-microphone ASR endpointing safeguards."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AsrEndpointingConfigTests(unittest.TestCase):
    def test_voice_config_exposes_independent_max_recording_deadline(self) -> None:
        source = (ROOT / "deps/SURF2026_VoiceModule-main/config/voice_config.py").read_text(
            encoding="utf-8"
        )
        module = ast.parse(source)
        config = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == "VoiceConfig"
        )
        fields = {
            target.id
            for node in config.body
            if isinstance(node, ast.AnnAssign)
            for target in [node.target]
            if isinstance(target, ast.Name)
        }
        self.assertIn("asr_max_recording_sec", fields)
        self.assertIn("asr_preroll_frames", fields)
        self.assertIn("followup_control_poll_sec", fields)

    def test_followup_window_resets_vad_before_the_next_user_speech_edge(self) -> None:
        source = (ROOT / "surf_voice_runtime.py").read_text(encoding="utf-8")
        open_window = source.split("    def _open_followup_window", 1)[1].split(
            "    def _close_followup_window", 1
        )[0]
        self.assertIn("self._vad.reset()", open_window)
        self.assertIn("def _asr_preroll", source)
        self.assertIn("CONFIG.followup_control_poll_sec", source)

    def test_vad_engine_can_forget_a_previous_speech_state(self) -> None:
        source = (ROOT / "deps/SURF2026_VoiceModule-main/vad/vad_engine.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def reset(self)", source)
        self.assertIn("self._is_speech = False", source)

    def test_vad_speech_does_not_cancel_the_max_recording_deadline(self) -> None:
        source = (ROOT / "surf_voice_runtime.py").read_text(encoding="utf-8")
        self.assertIn("CONFIG.asr_max_recording_sec", source)
        self.assertNotIn('self._cancel_asr_deadline("vad_speech")', source)

    def test_speaker_embedding_does_not_cancel_the_max_recording_deadline(self) -> None:
        source = (ROOT / "surf_voice_runtime.py").read_text(encoding="utf-8")
        self.assertNotIn('self._cancel_asr_deadline("speaker_embedding")', source)
        self.assertIn("def _arm_asr_max_recording_deadline", source)

    def test_launcher_exports_max_recording_deadline(self) -> None:
        source = (ROOT / "scripts/run_surf_voice_runtime.sh").read_text(encoding="utf-8")
        self.assertIn("VOICE_ASR_MAX_RECORDING_SEC", source)
        self.assertIn("VOICE_ASR_PREROLL_FRAMES", source)
        self.assertIn("VOICE_FOLLOWUP_CONTROL_POLL_SEC", source)

    def test_default_env_keeps_the_long_command_guard_separate_from_normal_vad_end(self) -> None:
        source = (ROOT / "config/default.env").read_text(encoding="utf-8")
        self.assertIn("VOICE_ASR_MAX_RECORDING_SEC", source)
        self.assertIn("VOICE_ASR_PREROLL_FRAMES", source)
        self.assertIn("VOICE_FOLLOWUP_CONTROL_POLL_SEC", source)


if __name__ == "__main__":
    unittest.main()
