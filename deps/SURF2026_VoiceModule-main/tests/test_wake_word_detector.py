from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from wake_word.wake_word_detector import CHUNK_BYTES, WakeWordDetector


def _make_detector(on_detected=None, threshold=0.5):
    if on_detected is None:
        on_detected = MagicMock()
    mock_model = MagicMock()
    mock_model.predict.return_value = {}
    with patch("wake_word.wake_word_detector.openwakeword.model.Model", return_value=mock_model):
        det = WakeWordDetector(on_detected=on_detected, threshold=threshold)
    det._model = mock_model
    return det, mock_model, on_detected


def test_push_audio_buffers_correctly():
    det, mock_model, _ = _make_detector()
    pcm = b"\x00" * CHUNK_BYTES
    det.push_audio(pcm)
    assert not det._queue.empty()


def test_start_and_stop_do_not_raise():
    det, _, _ = _make_detector()
    det.start()
    det.stop()


def test_on_detected_called_when_score_above_threshold():
    callback = MagicMock()
    det, mock_model, _ = _make_detector(on_detected=callback, threshold=0.5)
    mock_model.predict.return_value = {"hey_jarvis": 0.9}
    det.start()
    det.push_audio(b"\x00" * CHUNK_BYTES)
    time.sleep(0.3)
    det.stop()
    callback.assert_called_once_with("hey_jarvis")


def test_on_detected_not_called_below_threshold():
    callback = MagicMock()
    det, mock_model, _ = _make_detector(on_detected=callback, threshold=0.5)
    mock_model.predict.return_value = {"hey_jarvis": 0.3}
    det.start()
    det.push_audio(b"\x00" * CHUNK_BYTES)
    time.sleep(0.3)
    det.stop()
    callback.assert_not_called()


def test_faulty_on_detected_does_not_crash_run_thread():
    def bad_callback(word):
        raise RuntimeError("boom")

    det, mock_model, _ = _make_detector(on_detected=bad_callback, threshold=0.5)
    mock_model.predict.return_value = {"hey_jarvis": 0.9}
    det.start()
    det.push_audio(b"\x00" * CHUNK_BYTES)
    time.sleep(0.3)
    assert det._thread is not None and det._thread.is_alive()
    det.stop()
