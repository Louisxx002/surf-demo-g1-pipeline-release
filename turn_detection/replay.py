from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import json
from pathlib import Path

from turn_detection.models import TurnDecision, TurnDecisionType


@dataclass(frozen=True)
class ReplayEvent:
    event_id: str
    session_id: str
    turn_id: str
    timestamp_ms: float
    vad_state: str
    silence_ms: float
    partial_text: str
    final_text: str
    agent_playing: bool
    expected_decision: TurnDecisionType | None


Detector = Callable[[ReplayEvent], TurnDecision]


def load_timeline(path: str | Path) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    previous_timestamp: float | None = None
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                timestamp_ms = float(payload["timestamp_ms"])
                event_id = str(payload["event_id"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid timeline event on line {line_number}") from exc
            if previous_timestamp is not None and timestamp_ms < previous_timestamp:
                raise ValueError("timeline events must be in timestamp order")
            previous_timestamp = timestamp_ms
            expected = payload.get("expected_decision")
            events.append(
                ReplayEvent(
                    event_id=event_id,
                    session_id=str(payload.get("session_id", "")),
                    turn_id=str(payload.get("turn_id", "")),
                    timestamp_ms=timestamp_ms,
                    vad_state=str(payload.get("vad_state", "unknown")),
                    silence_ms=float(payload.get("silence_ms", 0)),
                    partial_text=str(payload.get("partial_text", "")),
                    final_text=str(payload.get("final_text", "")),
                    agent_playing=bool(payload.get("agent_playing", False)),
                    expected_decision=(
                        TurnDecisionType(expected) if expected is not None else None
                    ),
                )
            )
    return events


def replay_detector(
    events: Iterable[ReplayEvent], detector: Detector
) -> list[TurnDecision]:
    return [detector(event) for event in events]
