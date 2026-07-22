from __future__ import annotations

import json
import os
import threading
from pathlib import Path


BASIC_MODE = "basic"
SMART_MODE = "smart"
VALID_MODES = frozenset({BASIC_MODE, SMART_MODE})


def normalize_mode(mode: str) -> str:
    value = str(mode).strip().lower()
    if value not in VALID_MODES:
        raise ValueError(f"unsupported turn mode: {mode}")
    return value


class TurnModeStore:
    """Small durable store shared by the monitor and voice runtime."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> str:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return normalize_mode(payload.get("mode", BASIC_MODE))
        except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, TypeError):
            return BASIC_MODE

    def write(self, mode: str) -> str:
        value = normalize_mode(mode)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps({"mode": value}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return value


class RecordingEndpointController:
    """Chooses when a recording may finalize without owning ASR itself."""

    def __init__(self, smart_pause_grace_sec: float = 0.8) -> None:
        if smart_pause_grace_sec < 0:
            raise ValueError("smart_pause_grace_sec must be non-negative")
        self._lock = threading.Lock()
        self._mode = BASIC_MODE
        self._smart_pause_grace_sec = float(smart_pause_grace_sec)
        self._pending_silence = False
        self._pending_deadline = 0.0

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def begin(self, mode: str) -> None:
        with self._lock:
            self._mode = normalize_mode(mode)
            self._pending_silence = False
            self._pending_deadline = 0.0

    def on_vad(self, is_speech: bool, *, now: float, holdoff_until: float) -> bool:
        with self._lock:
            if is_speech:
                self._pending_silence = False
                self._pending_deadline = 0.0
                return False
            if self._mode == SMART_MODE:
                if not self._pending_silence:
                    self._pending_silence = True
                    self._pending_deadline = max(
                        holdoff_until,
                        now + self._smart_pause_grace_sec,
                    )
                return False
            if now > holdoff_until:
                self._pending_silence = False
                self._pending_deadline = 0.0
                return True
            return False

    def poll(self, *, now: float, holdoff_until: float) -> bool:
        with self._lock:
            if self._mode != SMART_MODE or not self._pending_silence:
                return False
            if now < max(holdoff_until, self._pending_deadline):
                return False
            self._pending_silence = False
            self._pending_deadline = 0.0
            return True
