from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable

from config.voice_config import CONFIG

logger = logging.getLogger(__name__)

Consumer = Callable[[bytes], None]


class AudioBus:
    """Thread-safe PCM broadcast bus with a rolling backtrack buffer.

    Producers call push(); registered consumers receive every chunk in the
    order they subscribed.  A 1-second rolling deque lets late consumers
    replay recent audio without blocking producers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumers: list[Consumer] = []
        max_chunks = int(CONFIG.bus_buffer_sec * 1000 / CONFIG.frame_ms)
        self._buffer: deque[bytes] = deque(maxlen=max_chunks)

    def register(self, consumer: Consumer) -> None:
        with self._lock:
            self._consumers.append(consumer)

    def unregister(self, consumer: Consumer) -> None:
        with self._lock:
            try:
                self._consumers.remove(consumer)
            except ValueError:
                pass

    def push(self, chunk: bytes) -> None:
        with self._lock:
            self._buffer.append(chunk)
            consumers = list(self._consumers)

        for consumer in consumers:
            try:
                consumer(chunk)
            except Exception:
                logger.exception("AudioBus consumer %r raised; skipping", consumer)

    def get_buffer(self) -> list[bytes]:
        with self._lock:
            return list(self._buffer)
