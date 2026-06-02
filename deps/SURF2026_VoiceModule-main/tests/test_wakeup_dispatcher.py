from __future__ import annotations

import time

import pytest

from wake_word.wakeup_dispatcher import WakeupDispatcher


def test_callback_fires_on_first_detection():
    d = WakeupDispatcher(dedup_sec=0.5)
    events: list[str] = []
    d.register(events.append)

    d.on_detection("hey jarvis")

    assert events == ["hey jarvis"]


def test_duplicate_within_window_suppressed():
    d = WakeupDispatcher(dedup_sec=0.5)
    events: list[str] = []
    d.register(events.append)

    d.on_detection("hey jarvis")
    d.on_detection("hey jarvis")  # within window → suppressed

    assert len(events) == 1


def test_event_after_window_passes_through():
    d = WakeupDispatcher(dedup_sec=0.05)
    events: list[str] = []
    d.register(events.append)

    d.on_detection("hey jarvis")
    time.sleep(0.06)
    d.on_detection("hey jarvis")

    assert len(events) == 2


def test_different_words_tracked_independently():
    d = WakeupDispatcher(dedup_sec=0.5)
    events: list[str] = []
    d.register(events.append)

    d.on_detection("hey jarvis")
    d.on_detection("alexa")  # different word → passes through

    assert events == ["hey jarvis", "alexa"]


def test_faulty_callback_does_not_stop_others():
    d = WakeupDispatcher(dedup_sec=0.5)
    good: list[str] = []

    def bad(_w: str) -> None:
        raise RuntimeError("fail")

    d.register(bad)
    d.register(good.append)

    d.on_detection("hey jarvis")

    assert good == ["hey jarvis"]


def test_unregister_removes_callback():
    d = WakeupDispatcher(dedup_sec=0.5)
    events: list[str] = []
    d.register(events.append)
    d.unregister(events.append)

    d.on_detection("hey jarvis")

    assert events == []
