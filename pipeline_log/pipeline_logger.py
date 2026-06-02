"""Session-based pipeline logging for wake-to-answer runs."""
from __future__ import annotations

import json
import logging
import os
import threading
import wave
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = Path(os.environ.get("PIPELINE_LOGS_DIR", str(PROJECT_ROOT / "logs")))


@dataclass
class SessionLog:
    session_id: str
    session_dir: Path
    _t0: float = field(default_factory=time.monotonic, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def log_path(self) -> Path:
        return self.session_dir / "pipeline.log"

    def _append(self, entry: dict[str, Any]) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record(self, stage: str, **kwargs: Any) -> float:
        elapsed = time.monotonic() - self._t0
        entry = {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "elapsed_sec": round(elapsed, 3),
            "stage": stage,
            **kwargs,
        }
        self._append(entry)
        logger.info("[%s] %s +%.3fs", self.session_id, stage, elapsed)
        return elapsed

    def record_duration(self, stage: str, start: float, **kwargs: Any) -> float:
        duration = time.monotonic() - start
        self.record(stage, duration_sec=round(duration, 3), **kwargs)
        return duration

    def save_audio(self, pcm_frames: list[bytes], sample_rate: int = 16000, channels: int = 1) -> None:
        wav_path = self.session_dir / "audio.wav"
        try:
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                for frame in pcm_frames:
                    wf.writeframes(frame)
            self.record("audio_saved", path=str(wav_path), frames=len(pcm_frames), sample_rate=sample_rate)
        except Exception as exc:
            logger.warning("audio save failed for %s: %s", self.session_id, exc)

    def flush(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)


class PipelineLogger:
    def __init__(self) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._counter = 0
        self._current: SessionLog | None = None

    def _new_session_id(self) -> str:
        self._counter += 1
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{ts}_s{self._counter:03d}"

    def start_session(self, wake_word: str) -> SessionLog:
        session_id = self._new_session_id()
        session_dir = LOGS_DIR / session_id
        session = SessionLog(session_id=session_id, session_dir=session_dir)
        with self._lock:
            self._current = session
        session.record("wake", wake_word=wake_word)
        return session

    def attach_session(self, session_id: str) -> SessionLog:
        session = SessionLog(session_id=session_id, session_dir=LOGS_DIR / session_id)
        with self._lock:
            self._current = session
        return session

    def end_session(self, reason: str = "session_end") -> None:
        with self._lock:
            session = self._current
            self._current = None
        if session is None:
            return
        session.record(reason)
        session.flush()

    @property
    def current(self) -> SessionLog | None:
        with self._lock:
            return self._current
