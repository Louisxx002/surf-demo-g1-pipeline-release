from __future__ import annotations

from unittest.mock import MagicMock, patch

from asr.asr_engine import ASREngine


def _make_engine(on_result=None):
    if on_result is None:
        on_result = MagicMock()
    mock_model = MagicMock()
    mock_model.generate.return_value = [{"text": "你好"}]
    with patch("asr.asr_engine.AutoModel", return_value=mock_model):
        engine = ASREngine(on_result=on_result)
    engine._model = mock_model
    return engine, mock_model, on_result


def test_start_clears_buffer():
    engine, _, _ = _make_engine()
    engine._buffer = b"\xff" * 100
    engine.start_recording()
    assert engine._buffer == b""


def test_initial_audio_prepended_to_buffer():
    engine, _, _ = _make_engine()
    prefill = b"\x01\x02" * 100
    engine.start_recording(initial_audio=prefill)
    assert engine._buffer == prefill
    assert engine._recording is True


def test_push_when_recording():
    engine, _, _ = _make_engine()
    engine.start_recording()
    engine.push_audio(b"\x01\x02")
    assert engine._buffer == b"\x01\x02"


def test_push_when_not_recording_ignored():
    engine, _, _ = _make_engine()
    engine.push_audio(b"\x01\x02")
    assert engine._buffer == b""


def test_stop_calls_model_and_callback():
    callback = MagicMock()
    engine, mock_model, _ = _make_engine(on_result=callback)
    mock_model.generate.return_value = [{"text": "你好"}]
    engine.start_recording()
    engine.push_audio(b"\x00" * 320)
    engine.stop_and_transcribe()
    mock_model.generate.assert_called_once()
    callback.assert_called_once_with("你好")


def test_empty_buffer_no_callback():
    callback = MagicMock()
    engine, mock_model, _ = _make_engine(on_result=callback)
    engine.start_recording()
    engine.stop_and_transcribe()
    mock_model.generate.assert_not_called()
    callback.assert_not_called()


def test_stop_when_not_recording_does_not_raise():
    engine, mock_model, callback = _make_engine()
    engine.stop_and_transcribe()
    mock_model.generate.assert_not_called()
