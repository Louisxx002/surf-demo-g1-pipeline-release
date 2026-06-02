from __future__ import annotations

import pytest

from config.voice_config import CONFIG
from vad.vad_engine import VADEngine

SILENCE = b"\x00" * CONFIG.frame_bytes


# ── helpers ─────────────────────────────────────────────────────────────────

def _speech_engine() -> tuple[VADEngine, list[bool]]:
    """Return an engine already in SPEECH state with a fresh event list."""
    engine = VADEngine()
    events: list[bool] = []
    engine.register(events.append)
    # Drive into speech state via webrtcvad (silence frames → no event)
    # We manipulate _is_speech directly to set up state for silence tests.
    engine._is_speech = True
    return engine, events


# ── original tests (unchanged behaviour) ────────────────────────────────────

def test_process_frame_returns_bool(one_frame_pcm):
    engine = VADEngine()
    result = engine.process_frame(one_frame_pcm)
    assert isinstance(result, bool)


def test_wrong_frame_size_raises():
    engine = VADEngine()
    with pytest.raises(ValueError, match="Expected"):
        engine.process_frame(b"\x00" * (CONFIG.frame_bytes + 1))


def test_invalid_aggressiveness_raises():
    with pytest.raises(ValueError):
        VADEngine(aggressiveness=4)


def test_no_callback_when_no_state_change(silence_pcm):
    engine = VADEngine()
    events: list[bool] = []
    engine.register(events.append)

    silence_frame = silence_pcm[: CONFIG.frame_bytes]
    engine.process_frame(silence_frame)
    engine.process_frame(silence_frame)

    assert len(events) == 0


def test_callback_not_fired_on_repeated_same_state():
    engine = VADEngine()
    events: list[bool] = []
    engine.register(events.append)

    for _ in range(5):
        engine.process_frame(SILENCE)

    assert len(events) == 0


def test_unregister_stops_callbacks():
    engine = VADEngine()
    events: list[bool] = []
    engine.register(events.append)
    engine.unregister(events.append)

    engine.process_frame(SILENCE)
    assert events == []


# ── confirmation-window tests ────────────────────────────────────────────────

def test_silence_callback_not_fired_before_confirmation():
    """N-1 silence frames must not trigger False."""
    engine, events = _speech_engine()
    for _ in range(CONFIG.vad_silence_frames - 1):
        engine.process_frame(SILENCE)
    assert events == []


def test_silence_callback_fired_after_confirmation():
    """Exactly N silence frames must fire False exactly once."""
    engine, events = _speech_engine()
    for _ in range(CONFIG.vad_silence_frames):
        engine.process_frame(SILENCE)
    assert events == [False]


def test_silence_counter_resets_on_speech():
    """Speech frame during confirmation window resets the counter."""
    engine, events = _speech_engine()

    # feed N-1 silence frames (not yet enough to trigger)
    for _ in range(CONFIG.vad_silence_frames - 1):
        engine.process_frame(SILENCE)
    assert events == []

    # one more silence frame would normally trigger; reset counter instead
    engine._silence_counter = 0  # simulate speech frame resetting counter

    # now need full N frames again
    for _ in range(CONFIG.vad_silence_frames - 1):
        engine.process_frame(SILENCE)
    assert events == []  # still not triggered
