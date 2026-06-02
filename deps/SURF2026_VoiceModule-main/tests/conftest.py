from __future__ import annotations

import math
import struct

import pytest

from config.voice_config import CONFIG


def _make_sine(freq: float = 440.0, duration_sec: float = 0.1) -> bytes:
    n = int(CONFIG.sample_rate * duration_sec)
    samples = [int(32767 * math.sin(2 * math.pi * freq * i / CONFIG.sample_rate)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


def _make_silence(duration_sec: float = 0.1) -> bytes:
    n = int(CONFIG.sample_rate * duration_sec)
    return b"\x00" * (n * 2)


@pytest.fixture
def sine_pcm() -> bytes:
    return _make_sine()


@pytest.fixture
def silence_pcm() -> bytes:
    return _make_silence()


@pytest.fixture
def one_frame_pcm() -> bytes:
    return _make_sine(duration_sec=CONFIG.frame_ms / 1000)
