from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import json


TURN_START_STAGES = {"asr_started", "followup_asr_started"}
REPLY_PLAY_STAGES = {"tts_play_started", "tts_play_finished"}


def parse_event_time_ms(event: dict[str, Any]) -> int | None:
    value = str(event.get("time", "")).strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def read_pipeline_events(log_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not log_path.exists():
        return events
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


@dataclass
class TurnBuilder:
    session_id: str
    turn_index: int
    events: list[dict[str, Any]] = field(default_factory=list)
    stage_times: dict[str, int] = field(default_factory=dict)
    asr_text: str = ""
    speaker: str = ""
    reply: str = ""
    action: dict[str, Any] = field(default_factory=dict)

    @property
    def turn_id(self) -> str:
        return f"{self.session_id}_t{self.turn_index:03d}"

    def add(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        stage = str(event.get("stage", ""))
        ts_ms = parse_event_time_ms(event)
        if ts_ms is not None and stage not in self.stage_times:
            self.stage_times[stage] = ts_ms

        if stage == "speaker_id":
            self.speaker = str(event.get("label", self.speaker) or self.speaker)
        elif stage in {"asr_result", "asr_received"}:
            self.asr_text = str(event.get("text", self.asr_text) or self.asr_text)
            self.speaker = str(event.get("speaker", self.speaker) or self.speaker)
        elif stage == "llm_reply":
            self.reply = str(event.get("reply", self.reply) or self.reply)
        elif stage == "action_result":
            self.action = {
                "label": event.get("label", ""),
                "official_name": event.get("official_name", ""),
                "action_id": event.get("action_id", ""),
                "executed": event.get("executed", ""),
                "reason": event.get("reason", ""),
                "score": event.get("score", ""),
            }

    def latency(self, start_stage: str, end_stage: str) -> int | None:
        start = self.stage_times.get(start_stage)
        end = self.stage_times.get(end_stage)
        if start is None or end is None:
            return None
        return max(0, end - start)

    def summary(self) -> dict[str, Any]:
        record_start = self.stage_times.get("asr_started", self.stage_times.get("followup_asr_started"))
        play_finished = self.stage_times.get("tts_play_finished")
        turn_total = max(0, play_finished - record_start) if record_start is not None and play_finished is not None else None
        asr_start_stage = "asr_started" if "asr_started" in self.stage_times else "followup_asr_started"

        return {
            "stage": "turn_summary",
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "turn_index": self.turn_index,
            "asr_text": self.asr_text,
            "speaker": self.speaker,
            "reply": self.reply,
            "action": self.action,
            "latency_ms": {
                "asr_record": self.latency(asr_start_stage, "asr_result"),
                "asr_to_llm_reply": self.latency("asr_received", "llm_reply"),
                "llm_to_tts_ready": self.latency("llm_reply", "tts_ready"),
                "tts_play": self.latency("tts_play_started", "tts_play_finished"),
                "action_after_tts": self.latency("tts_ready", "action_result"),
                "turn_total": turn_total,
            },
            "stage_times": self.stage_times,
        }


def _event_session_id(event: dict[str, Any], fallback: str) -> str:
    return str(event.get("session_id") or fallback or "default")


def _is_reply_play_event(event: dict[str, Any]) -> bool:
    return event.get("stage") in REPLY_PLAY_STAGES and str(event.get("kind", "")) == "reply"


def build_turn_summaries(events: list[dict[str, Any]], fallback_session_id: str = "default") -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    current: TurnBuilder | None = None
    turn_index_by_session: dict[str, int] = {}

    def finish_current() -> None:
        nonlocal current
        if current and (current.asr_text or current.reply):
            summaries.append(current.summary())
        current = None

    for event in events:
        stage = str(event.get("stage", ""))
        session_id = _event_session_id(event, current.session_id if current else fallback_session_id)

        if stage in TURN_START_STAGES:
            finish_current()
            turn_index_by_session[session_id] = turn_index_by_session.get(session_id, 0) + 1
            current = TurnBuilder(session_id=session_id, turn_index=turn_index_by_session[session_id])
            current.add(event)
            continue

        if current is None and stage in {"asr_result", "asr_received", "llm_reply"}:
            turn_index_by_session[session_id] = turn_index_by_session.get(session_id, 0) + 1
            current = TurnBuilder(session_id=session_id, turn_index=turn_index_by_session[session_id])

        if current is None:
            continue

        if _is_reply_play_event(event):
            current.add(event)
            if stage == "tts_play_finished":
                finish_current()
            continue

        if stage in {
            "speaker_id",
            "audio_saved",
            "asr_result",
            "asr_received",
            "thinking",
            "llm_reply",
            "tts_ready",
            "action_result",
            "action_skipped",
            "session_end",
        }:
            current.add(event)

    finish_current()
    return summaries


def read_turn_summaries(log_path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    summaries = build_turn_summaries(read_pipeline_events(log_path), fallback_session_id=log_path.parent.name)
    if limit and len(summaries) > limit:
        return summaries[-limit:]
    return summaries
