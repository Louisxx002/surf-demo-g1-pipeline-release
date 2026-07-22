import threading
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
VOICE_MODULE = ROOT / "deps" / "SURF2026_VoiceModule-main"
sys.path.insert(0, str(VOICE_MODULE))

from surf_voice_runtime import SurfVoiceRuntime
from turn_detection.mode_control import RecordingEndpointController, SMART_MODE


class TurnModeRuntimeTests(unittest.TestCase):
    def make_runtime(self):
        runtime = SurfVoiceRuntime.__new__(SurfVoiceRuntime)
        runtime._recording = True
        runtime._recording_lock = threading.Lock()
        runtime._asr_deadline = 99.0
        runtime._asr_audio_frames = []
        runtime._asr = Mock()
        runtime._save_audio = Mock()
        runtime._session_log = None
        runtime._endpoint_controller = RecordingEndpointController(smart_pause_grace_sec=0.8)
        runtime._endpoint_controller.begin(SMART_MODE)
        runtime._vad_holdoff_until = 10.0
        return runtime

    def test_finalize_recording_is_idempotent(self):
        runtime = self.make_runtime()

        self.assertTrue(runtime._finalize_recording("first"))
        self.assertFalse(runtime._finalize_recording("duplicate"))

        runtime._save_audio.assert_called_once_with()
        runtime._asr.stop_and_transcribe.assert_called_once_with()
        self.assertEqual(runtime._asr_deadline, 0.0)

    def test_smart_pending_silence_finalizes_from_poll(self):
        runtime = self.make_runtime()
        runtime._endpoint_controller.on_vad(False, now=10.1, holdoff_until=10.0)

        self.assertFalse(runtime._poll_recording_endpoint(now=10.89))
        self.assertTrue(runtime._poll_recording_endpoint(now=10.91))

        runtime._asr.stop_and_transcribe.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
