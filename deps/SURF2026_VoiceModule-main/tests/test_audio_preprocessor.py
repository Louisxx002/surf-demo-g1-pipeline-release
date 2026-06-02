from __future__ import annotations

import numpy as np

from audio.audio_preprocessor import NoiseReduceProcessor
from config.voice_config import CONFIG


def _make_noisy_pcm(duration_sec: float = 0.1) -> bytes:
    n = int(CONFIG.sample_rate * duration_sec)
    t = np.linspace(0, duration_sec, n, endpoint=False)
    signal = np.sin(2 * np.pi * 440 * t) * 32767 * 0.5
    noise = np.random.default_rng(0).standard_normal(n) * 3000
    return (signal + noise).astype(np.int16).tobytes()


def test_output_same_length_as_input():
    proc = NoiseReduceProcessor()
    raw = _make_noisy_pcm()
    assert len(proc.process(raw)) == len(raw)


def test_output_is_bytes():
    proc = NoiseReduceProcessor()
    assert isinstance(proc.process(_make_noisy_pcm()), bytes)


def test_on_far_end_does_not_raise():
    proc = NoiseReduceProcessor()
    proc.on_far_end(b"\x00" * CONFIG.frame_bytes)
