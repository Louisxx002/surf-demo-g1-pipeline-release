from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
import json
import os
import threading

import pytest

from turn_detection import TurnDecision, TurnDecisionObserver, TurnDecisionType


class BrokenStripStr(str):
    def strip(self, *_args, **_kwargs):
        raise RuntimeError("bad strip")


class UnhashableStr(str):
    __hash__ = None


def make_decision(event_id: str = "event-001") -> TurnDecision:
    return TurnDecision(
        event_id=event_id,
        session_id="session-001",
        turn_id="turn-001",
        timestamp=1721476800.0,
        decision=TurnDecisionType.END_OF_TURN,
        confidence=0.92,
        reason="final transcript and silence",
        vad_state="silence",
        partial_text="hello",
        final_text="hello there",
        agent_playing=False,
        detector_name="baseline",
        detector_latency_ms=4.5,
    )


def test_turn_decision_has_five_outcomes_and_is_immutable() -> None:
    assert {decision.value for decision in TurnDecisionType} == {
        "CONTINUE_SPEAKING",
        "END_OF_TURN",
        "TRUE_INTERRUPT",
        "BACKCHANNEL",
        "UNCERTAIN",
    }
    assert {field.name for field in fields(TurnDecision)} == {
        "event_id",
        "session_id",
        "turn_id",
        "timestamp",
        "decision",
        "confidence",
        "reason",
        "vad_state",
        "partial_text",
        "final_text",
        "agent_playing",
        "detector_name",
        "detector_latency_ms",
    }

    decision = make_decision()
    with pytest.raises(FrozenInstanceError):
        decision.reason = "changed"  # type: ignore[misc]


def test_observer_only_appends_decision_as_jsonl(tmp_path) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    observer = TurnDecisionObserver(output_path)
    assert not output_path.exists()

    assert observer.observe(make_decision()) is True

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "event_id": "event-001",
        "session_id": "session-001",
        "turn_id": "turn-001",
        "timestamp": 1721476800.0,
        "decision": "END_OF_TURN",
        "confidence": 0.92,
        "reason": "final transcript and silence",
        "vad_state": "silence",
        "partial_text": "hello",
        "final_text": "hello there",
        "agent_playing": False,
        "detector_name": "baseline",
        "detector_latency_ms": 4.5,
    }


def test_observer_deduplicates_events_by_stable_event_id(tmp_path) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    observer = TurnDecisionObserver(output_path)
    event = make_decision()

    assert observer.observe(event) is True
    assert observer.observe(event) is False

    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_observer_rebuilds_deduplication_from_existing_jsonl(tmp_path) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    event = make_decision()

    assert TurnDecisionObserver(output_path).observe(event) is True
    assert TurnDecisionObserver(output_path).observe(event) is False

    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_observers_serialize_concurrent_duplicate_appends(tmp_path) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    observers = [TurnDecisionObserver(output_path), TurnDecisionObserver(output_path)]
    barrier = threading.Barrier(2)

    def append(observer: TurnDecisionObserver) -> bool:
        barrier.wait(timeout=2)
        return observer.observe(make_decision())

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, observers))

    assert sorted(results) == [False, True]
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize("bad_event", [None, {}, {"event_id": "event-001"}])
def test_observer_swallows_bad_or_incomplete_events(tmp_path, bad_event) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    observer = TurnDecisionObserver(output_path)

    assert observer.observe(bad_event) is False
    assert not output_path.exists()


def test_observer_rejects_empty_event_id(tmp_path) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    observer = TurnDecisionObserver(output_path)

    assert observer.observe(make_decision(event_id="")) is False
    assert not output_path.exists()


@pytest.mark.parametrize(
    "event_id",
    [BrokenStripStr("event-001"), UnhashableStr("event-001")],
)
def test_observer_isolates_malformed_event_id_errors(tmp_path, event_id) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    observer = TurnDecisionObserver(output_path)

    assert observer.observe(make_decision(event_id=event_id)) is False
    assert not output_path.exists()


def test_observer_swallows_write_errors_without_losing_event_id(tmp_path) -> None:
    output_path = tmp_path / "missing" / "turn_shadow.jsonl"
    observer = TurnDecisionObserver(output_path)
    event = make_decision()

    assert observer.observe(event) is False

    output_path.parent.mkdir()
    assert observer.observe(event) is True
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_observer_rolls_back_partial_single_write(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    observer = TurnDecisionObserver(output_path)
    event = make_decision()
    real_write = os.write

    def partial_write(fd: int, data: bytes) -> int:
        return real_write(fd, data[: len(data) // 2])

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", partial_write)
        assert observer.observe(event) is False

    assert output_path.read_bytes() == b""
    assert observer.observe(event) is True
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_observer_repairs_valid_json_without_trailing_newline(tmp_path) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    first = make_decision(event_id="event-001")
    output_path.write_text(
        json.dumps({**first.__dict__, "decision": first.decision.value}),
        encoding="utf-8",
    )

    observer = TurnDecisionObserver(output_path)
    assert observer.observe(make_decision(event_id="event-002")) is True

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event_id"] for line in lines] == [
        "event-001",
        "event-002",
    ]


def test_observer_truncates_incomplete_tail_before_append(tmp_path) -> None:
    output_path = tmp_path / "turn_shadow.jsonl"
    output_path.write_bytes(b'{"event_id":"event-001"}\n{"event_id":')

    observer = TurnDecisionObserver(output_path)
    assert observer.observe(make_decision(event_id="event-002")) is True

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event_id"] for line in lines] == [
        "event-001",
        "event-002",
    ]
