from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from audio.audio_bus import AudioBus
from audio.mic_capture import MicCapture
from config.voice_config import CONFIG


def _make_capture(bus=None):
    if bus is None:
        bus = MagicMock(spec=AudioBus)
    with patch("audio.mic_capture.sd.InputStream"):
        cap = MicCapture(bus=bus)
    return cap, bus


def test_start_and_stop_do_not_raise():
    cap, _ = _make_capture()
    with patch("audio.mic_capture.sd.InputStream") as mock_stream_cls:
        mock_stream = MagicMock()
        mock_stream_cls.return_value = mock_stream
        cap.start()
        cap.stop()
    mock_stream.start.assert_called_once()
    mock_stream.stop.assert_called_once()


def test_callback_pushes_frames_to_bus():
    bus = MagicMock(spec=AudioBus)
    cap, _ = _make_capture(bus=bus)
    # 恰好一帧的数据
    n_samples = CONFIG.frame_bytes // 2
    indata = np.zeros((n_samples, 1), dtype=np.float32)
    cap._callback(indata, n_samples, None, None)
    bus.push.assert_called_once()
    assert len(bus.push.call_args[0][0]) == CONFIG.frame_bytes


def test_short_callback_does_not_push_incomplete():
    bus = MagicMock(spec=AudioBus)
    cap, _ = _make_capture(bus=bus)
    # 不足一帧
    indata = np.zeros((1, 1), dtype=np.float32)
    cap._callback(indata, 1, None, None)
    bus.push.assert_not_called()


def test_two_frames_in_one_callback():
    bus = MagicMock(spec=AudioBus)
    cap, _ = _make_capture(bus=bus)
    # 两帧的数据一次性到达
    n_samples = (CONFIG.frame_bytes // 2) * 2
    indata = np.zeros((n_samples, 1), dtype=np.float32)
    cap._callback(indata, n_samples, None, None)
    assert bus.push.call_count == 2
