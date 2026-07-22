from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from turn_detection.mode_control import (
    BASIC_MODE,
    SMART_MODE,
    RecordingEndpointController,
    TurnModeStore,
)


class TurnModeStoreTests(unittest.TestCase):
    def test_missing_file_defaults_to_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TurnModeStore(Path(tmp) / "turn_mode.json")
            self.assertEqual(store.read(), BASIC_MODE)

    def test_write_persists_normalized_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "turn_mode.json"
            store = TurnModeStore(path)
            store.write(SMART_MODE)
            self.assertEqual(store.read(), SMART_MODE)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["mode"], SMART_MODE)

    def test_invalid_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TurnModeStore(Path(tmp) / "turn_mode.json")
            with self.assertRaises(ValueError):
                store.write("experimental")


class RecordingEndpointControllerTests(unittest.TestCase):
    def test_basic_mode_preserves_ignored_falling_edge_during_holdoff(self) -> None:
        controller = RecordingEndpointController()
        controller.begin(BASIC_MODE)
        self.assertFalse(controller.on_vad(False, now=1.0, holdoff_until=2.0))
        self.assertFalse(controller.poll(now=2.1, holdoff_until=2.0))

    def test_smart_mode_finalizes_only_after_pause_grace(self) -> None:
        controller = RecordingEndpointController(smart_pause_grace_sec=0.8)
        controller.begin(SMART_MODE)
        self.assertFalse(controller.on_vad(False, now=2.1, holdoff_until=2.0))
        self.assertFalse(controller.poll(now=2.89, holdoff_until=2.0))
        self.assertTrue(controller.poll(now=2.91, holdoff_until=2.0))
        self.assertFalse(controller.poll(now=3.0, holdoff_until=2.0))

    def test_smart_mode_cancels_pending_end_when_speech_resumes(self) -> None:
        controller = RecordingEndpointController(smart_pause_grace_sec=0.8)
        controller.begin(SMART_MODE)
        controller.on_vad(False, now=2.1, holdoff_until=2.0)
        controller.on_vad(True, now=2.5, holdoff_until=2.0)
        self.assertFalse(controller.poll(now=3.0, holdoff_until=2.0))

    def test_repeated_silence_does_not_extend_smart_pause_grace(self) -> None:
        controller = RecordingEndpointController(smart_pause_grace_sec=0.8)
        controller.begin(SMART_MODE)
        controller.on_vad(False, now=2.1, holdoff_until=2.0)
        controller.on_vad(False, now=2.7, holdoff_until=2.0)
        self.assertTrue(controller.poll(now=2.91, holdoff_until=2.0))

    def test_basic_mode_ends_immediately_after_holdoff(self) -> None:
        controller = RecordingEndpointController(smart_pause_grace_sec=0.8)
        controller.begin(BASIC_MODE)
        self.assertTrue(controller.on_vad(False, now=2.1, holdoff_until=2.0))


if __name__ == "__main__":
    unittest.main()
