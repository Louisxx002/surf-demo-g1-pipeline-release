from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from wake_word.chinese_wake_word_detector import CHUNK_BYTES, ChineseWakeWordDetector


def _make_detector(on_detected=None):
    if on_detected is None:
        on_detected = MagicMock()
    with patch("wake_word.chinese_wake_word_detector.sherpa_onnx") as mock_shnx, \
         patch("wake_word.chinese_wake_word_detector._find_model_file", return_value="fake.onnx"):
        mock_kws = MagicMock()
        mock_stream = MagicMock()
        mock_kws.create_stream.return_value = mock_stream
        mock_kws.is_ready.return_value = False  # prevent infinite while loop
        mock_kws.get_result.return_value = ""
        mock_shnx.KeywordSpotter.return_value = mock_kws
        det = ChineseWakeWordDetector(on_detected=on_detected)
    return det, on_detected


def _pcm(n_bytes: int) -> bytes:
    return b"\x00" * n_bytes


# ── tests ────────────────────────────────────────────────────────────────────

def test_push_before_start_does_not_infer():
    det, cb = _make_detector()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.05)
    det._kws.decode_stream.assert_not_called()
    cb.assert_not_called()


def test_detection_fires_callback():
    cb = MagicMock()
    det, _ = _make_detector(on_detected=cb)
    det._kws.get_result.return_value = "你好小G"

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()

    cb.assert_called_once_with("你好小G")


def test_no_detection_no_callback():
    cb = MagicMock()
    det, _ = _make_detector(on_detected=cb)
    det._kws.get_result.return_value = ""

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()

    cb.assert_not_called()


def test_stream_reset_after_detection():
    """检测到后应 reset stream，防止同一帧连续触发。"""
    det, _ = _make_detector()
    det._kws.get_result.return_value = "你好小G"

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()

    det._kws.reset_stream.assert_called()


def test_callback_exception_does_not_crash():
    cb = MagicMock(side_effect=RuntimeError("boom"))
    det, _ = _make_detector(on_detected=cb)
    det._kws.get_result.return_value = "你好小G"

    det.start()
    det.push_audio(_pcm(CHUNK_BYTES))
    time.sleep(0.3)
    det.stop()  # should not raise
