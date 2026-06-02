from __future__ import annotations

import logging
import time
from typing import Callable

from config.voice_config import CONFIG

logger = logging.getLogger(__name__)

WakeCallback = Callable[[str], None]


class WakeupDispatcher:
    """Deduplicate wake-word events and broadcast to registered callbacks.

    When the same wake word fires multiple times within `dedup_sec` seconds,
    only the first event is forwarded.  Different wake words are tracked
    independently.
    """

    def __init__(self, dedup_sec: float | None = None) -> None:
        self._dedup_sec = dedup_sec if dedup_sec is not None else CONFIG.wakeup_dedup_sec
        self._callbacks: list[WakeCallback] = []
        self._last_fire: dict[str, float] = {}

    def register(self, callback: WakeCallback) -> None:
        self._callbacks.append(callback)

    def unregister(self, callback: WakeCallback) -> None:
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def on_detection(self, word: str) -> None:
        """Called by the wake-word detector with the matched keyword."""
        now = time.monotonic()
        last = self._last_fire.get(word, 0.0)
        if now - last < self._dedup_sec:
            return
        self._last_fire[word] = now
        for cb in list(self._callbacks):
            try:
                cb(word)
            except Exception:
                logger.exception("WakeupDispatcher callback %r raised", cb)
