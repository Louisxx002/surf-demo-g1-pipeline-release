from __future__ import annotations

import logging
from typing import Callable

import webrtcvad

from config.voice_config import CONFIG

logger = logging.getLogger(__name__)

VADCallback = Callable[[bool], None]


class VADEngine:
    """Frame-level voice activity detector backed by webrtcvad.

    Accepts exactly CONFIG.frame_bytes of raw 16-bit mono PCM per call.
    Fires registered callbacks on state transitions:
    - True  (rising edge)  : first speech frame after silence — immediate
    - False (falling edge) : after CONFIG.vad_silence_frames consecutive
                             silence frames — prevents false end-of-speech
                             from brief pauses during natural conversation
    """

    def __init__(self, aggressiveness: int = 2) -> None:
        if not 0 <= aggressiveness <= 3:
            raise ValueError(f"aggressiveness must be 0-3, got {aggressiveness}")
        self._vad = webrtcvad.Vad(aggressiveness)
        self._callbacks: list[VADCallback] = []
        self._is_speech: bool = False
        self._silence_counter: int = 0

    def register(self, callback: VADCallback) -> None:
        self._callbacks.append(callback)

    def unregister(self, callback: VADCallback) -> None:
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def reset(self) -> None:
        """Forget residual speech state without emitting a synthetic VAD edge."""
        self._is_speech = False
        self._silence_counter = 0


    def process_frame(self, frame: bytes) -> bool:
        """Process one PCM frame; return confirmed speech state."""
        if len(frame) != CONFIG.frame_bytes:
            raise ValueError(
                f"Expected {CONFIG.frame_bytes} bytes, got {len(frame)}"
            )
        raw = self._vad.is_speech(frame, CONFIG.sample_rate)

        if raw:
            self._silence_counter = 0
            if not self._is_speech:
                self._is_speech = True
                self._notify(True)
        else:
            if self._is_speech:
                self._silence_counter += 1
                if self._silence_counter >= CONFIG.vad_silence_frames:
                    self._is_speech = False
                    self._silence_counter = 0
                    self._notify(False)

        return self._is_speech

    def _notify(self, state: bool) -> None:
        for cb in list(self._callbacks):
            try:
                cb(state)
            except Exception:
                logger.exception("VADEngine callback %r raised", cb)
