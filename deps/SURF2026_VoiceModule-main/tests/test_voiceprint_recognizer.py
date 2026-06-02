from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from config.voice_config import CONFIG
from voice_id.voiceprint_recognizer import VoiceprintRecognizer


def _make_recognizer(on_embedding=None, capture_sec=0.1):
    if on_embedding is None:
        on_embedding = MagicMock()
    mock_inference = MagicMock()
    mock_inference.return_value = np.zeros(256, dtype=np.float32)
    with patch("voice_id.voiceprint_recognizer.Model.from_pretrained"), \
         patch("voice_id.voiceprint_recognizer.Inference", return_value=mock_inference):
        rec = VoiceprintRecognizer(on_embedding=on_embedding, capture_sec=capture_sec)
    rec._inference = mock_inference
    return rec, mock_inference, on_embedding


def _make_pcm(sec: float) -> bytes:
    n = int(CONFIG.sample_rate * sec)
    return (np.zeros(n, dtype=np.int16)).tobytes()


def test_start_capture_resets_buffer():
    rec, _, _ = _make_recognizer()
    rec._buffer = b"\xff" * 100
    rec._capturing = False
    rec.start_capture()
    assert rec._buffer == b""
    assert rec._capturing is True


def test_push_before_start_ignored():
    rec, mock_inf, callback = _make_recognizer()
    rec.push_audio(_make_pcm(0.05))
    mock_inf.assert_not_called()
    callback.assert_not_called()


def test_short_audio_does_not_trigger():
    rec, mock_inf, callback = _make_recognizer(capture_sec=0.1)
    rec.start_capture()
    rec.push_audio(_make_pcm(0.05))  # 只给一半
    assert rec._capturing is True
    mock_inf.assert_not_called()


def test_initial_audio_counts_toward_capture():
    import time
    callback = MagicMock()
    rec, mock_inf, _ = _make_recognizer(on_embedding=callback, capture_sec=0.1)
    mock_inf.return_value = np.zeros(256, dtype=np.float32)
    # 预填 0.08s（不足 capture_sec），再 push 0.05s → 合计超过 0.1s，应触发
    rec.start_capture(initial_audio=_make_pcm(0.08))
    rec.push_audio(_make_pcm(0.05))
    time.sleep(0.3)
    callback.assert_called_once()


def test_start_capture_default_still_resets_buffer():
    rec, _, _ = _make_recognizer()
    rec._buffer = b"\xff" * 100
    rec.start_capture()          # 无参数，等同原来行为
    assert rec._buffer == b""
    assert rec._capturing is True


def test_callback_called_after_capture_sec():
    import time
    callback = MagicMock()
    rec, mock_inf, _ = _make_recognizer(on_embedding=callback, capture_sec=0.1)
    mock_inf.return_value = np.zeros(256, dtype=np.float32)
    rec.start_capture()
    rec.push_audio(_make_pcm(0.15))  # 超过 capture_sec
    time.sleep(0.3)  # 等待后台线程
    callback.assert_called_once()
    embedding = callback.call_args[0][0]
    assert isinstance(embedding, np.ndarray)
    assert embedding.shape == (256,)
