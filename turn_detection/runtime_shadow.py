from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import count
from pathlib import Path
import queue
import threading
import time

from turn_detection.baseline_detector import BaselineDetector
from turn_detection.dynamic_detector import DynamicV1Detector
from turn_detection.observer import TurnDecisionObserver
from turn_detection.replay import ReplayEvent


@dataclass(frozen=True)
class _ShadowEvent:
    event_id: str
    kind: str
    timestamp: float
    value: object
    agent_playing: bool | Callable[[], bool]


class TurnShadowRuntime:
    def __init__(
        self,
        session_log: object | None,
        enabled: bool = False,
        queue_size: int = 128,
    ) -> None:
        self._queue: queue.Queue[_ShadowEvent] = queue.Queue(maxsize=max(1, queue_size))
        self._closed = threading.Event()
        self._sequence = count(1)
        self.dropped_count = 0
        self._session_id = str(getattr(session_log, "session_id", ""))
        session_dir = getattr(session_log, "session_dir", None)
        self._enabled = bool(enabled and self._session_id and session_dir is not None)
        self._observer = (
            TurnDecisionObserver(Path(session_dir) / "turn_shadow.jsonl")
            if self._enabled
            else None
        )
        self._thread: threading.Thread | None = None
        if self._enabled:
            self._thread = threading.Thread(
                target=self._run,
                name=f"turn-shadow-{self._session_id}",
                daemon=True,
            )
            self._thread.start()

    def submit_wake(
        self,
        word: str,
        *,
        agent_playing: bool | Callable[[], bool] = False,
    ) -> None:
        self._submit("wake", word, agent_playing)

    def submit_vad(
        self,
        is_speech: bool,
        *,
        agent_playing: bool | Callable[[], bool],
    ) -> None:
        self._submit("vad", bool(is_speech), agent_playing)

    def submit_asr_final(
        self,
        text: str,
        *,
        agent_playing: bool | Callable[[], bool],
    ) -> None:
        self._submit("asr_final", text, agent_playing)

    def submit_agent_playing(self, active: bool) -> None:
        self._submit("agent_playing", bool(active), active)

    def close(self) -> None:
        try:
            self._closed.set()
            if self._thread is not None:
                self._thread.join(timeout=2.0)
        except Exception:
            return None

    def _submit(
        self,
        kind: str,
        value: object,
        agent_playing: bool | Callable[[], bool],
    ) -> None:
        if not self._enabled or self._closed.is_set():
            return
        try:
            sequence = next(self._sequence)
            event = _ShadowEvent(
                event_id=f"{self._session_id}:{sequence:08d}:{kind}",
                kind=kind,
                timestamp=time.time(),
                value=value,
                agent_playing=agent_playing,
            )
            self._queue.put_nowait(event)
        except Exception:
            self.dropped_count += 1

    def _run(self) -> None:
        vad_state = "unknown"
        silence_started_at: float | None = None
        detectors = []
        for detector_type in (BaselineDetector, DynamicV1Detector):
            try:
                detectors.append(detector_type())
            except Exception:
                continue
        while not self._closed.is_set() or not self._queue.empty():
            try:
                event = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                if event.kind == "vad":
                    vad_state = "speech" if event.value else "silence"
                    silence_started_at = None if event.value else event.timestamp
                silence_ms = (
                    max(0.0, (event.timestamp - silence_started_at) * 1000)
                    if silence_started_at is not None
                    else 0.0
                )
                try:
                    agent_playing = (
                        event.agent_playing()
                        if callable(event.agent_playing)
                        else bool(event.agent_playing)
                    )
                except Exception:
                    agent_playing = False
                replay_event = ReplayEvent(
                    event_id=event.event_id,
                    session_id=self._session_id,
                    turn_id="turn-001",
                    timestamp_ms=event.timestamp * 1000,
                    vad_state=vad_state,
                    silence_ms=silence_ms,
                    partial_text="",
                    final_text=str(event.value) if event.kind == "asr_final" else "",
                    agent_playing=agent_playing,
                    expected_decision=None,
                )
                for detector in detectors:
                    try:
                        started = time.perf_counter()
                        decision = detector(replay_event)
                        latency_ms = (time.perf_counter() - started) * 1000
                        if self._observer is not None:
                            self._observer.observe(
                                replace(
                                    decision,
                                    event_id=f"{event.event_id}:{detector.name}",
                                    detector_latency_ms=latency_ms,
                                )
                            )
                    except Exception:
                        continue
            except Exception:
                pass
            finally:
                self._queue.task_done()
