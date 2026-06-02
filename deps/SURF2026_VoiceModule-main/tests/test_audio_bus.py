from __future__ import annotations

import threading
import time

import pytest

from audio.audio_bus import AudioBus
from config.voice_config import CONFIG


def test_consumer_receives_pushed_chunk(one_frame_pcm):
    bus = AudioBus()
    received: list[bytes] = []
    bus.register(received.append)

    bus.push(one_frame_pcm)

    assert received == [one_frame_pcm]


def test_multiple_consumers_all_receive(one_frame_pcm):
    bus = AudioBus()
    a: list[bytes] = []
    b: list[bytes] = []
    bus.register(a.append)
    bus.register(b.append)

    bus.push(one_frame_pcm)

    assert a == [one_frame_pcm]
    assert b == [one_frame_pcm]


def test_faulty_consumer_does_not_break_others(one_frame_pcm):
    bus = AudioBus()
    good: list[bytes] = []

    def bad(_chunk: bytes) -> None:
        raise RuntimeError("boom")

    bus.register(bad)
    bus.register(good.append)

    bus.push(one_frame_pcm)  # must not raise

    assert good == [one_frame_pcm]


def test_unregister_stops_delivery(one_frame_pcm):
    bus = AudioBus()
    received: list[bytes] = []
    bus.register(received.append)
    bus.unregister(received.append)

    bus.push(one_frame_pcm)

    assert received == []


def test_backtrack_buffer_contains_recent_chunks(one_frame_pcm):
    bus = AudioBus()
    chunks = [one_frame_pcm] * 3
    for c in chunks:
        bus.push(c)

    buf = bus.get_buffer()
    assert buf == chunks


def test_thread_safety_concurrent_push():
    bus = AudioBus()
    counts: list[int] = [0]
    lock = threading.Lock()

    def counter(_chunk: bytes) -> None:
        with lock:
            counts[0] += 1

    bus.register(counter)
    chunk = b"\x00" * CONFIG.frame_bytes

    threads = [threading.Thread(target=bus.push, args=(chunk,)) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counts[0] == 50
