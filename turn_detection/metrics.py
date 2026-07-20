from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from statistics import mean, median

from turn_detection.models import TurnDecision, TurnDecisionType
from turn_detection.replay import ReplayEvent


def summarize_comparison(
    events: Sequence[ReplayEvent],
    detector_runs: Mapping[str, Sequence[TurnDecision]],
) -> dict[str, object]:
    if len(detector_runs) != 2:
        raise ValueError("comparison requires exactly two detector runs")

    runs = {name: list(decisions) for name, decisions in detector_runs.items()}
    event_ids = [event.event_id for event in events]
    for name, decisions in runs.items():
        if [decision.event_id for decision in decisions] != event_ids:
            raise ValueError(f"{name} decisions do not align with replay events")

    first, second = runs.values()
    agreed = sum(
        left.decision is right.decision for left, right in zip(first, second)
    )
    total = len(events)

    false_end: dict[str, int] = {}
    missed_end: dict[str, int] = {}
    missed_interrupt: dict[str, int] = {}
    false_interrupt: dict[str, int] = {}
    backchannel_false_interrupt: dict[str, int] = {}
    playback_false_interrupt: dict[str, int] = {}
    delta_ms: dict[str, dict[str, float | int | None]] = {}
    reference_end_by_turn = {
        event.turn_id: event.timestamp_ms
        for event in events
        if event.expected_decision is TurnDecisionType.END_OF_TURN
    }

    for name, decisions in runs.items():
        false_end[name] = sum(
            decision.decision is TurnDecisionType.END_OF_TURN
            and event.expected_decision is not TurnDecisionType.END_OF_TURN
            for event, decision in zip(events, decisions)
        )
        missed_end[name] = sum(
            event.expected_decision is TurnDecisionType.END_OF_TURN
            and decision.decision is not TurnDecisionType.END_OF_TURN
            for event, decision in zip(events, decisions)
        )
        missed_interrupt[name] = sum(
            event.expected_decision is TurnDecisionType.TRUE_INTERRUPT
            and decision.decision is not TurnDecisionType.TRUE_INTERRUPT
            for event, decision in zip(events, decisions)
        )
        false_interrupt[name] = sum(
            decision.decision is TurnDecisionType.TRUE_INTERRUPT
            and event.expected_decision is not TurnDecisionType.TRUE_INTERRUPT
            for event, decision in zip(events, decisions)
        )
        backchannel_false_interrupt[name] = sum(
            event.expected_decision is TurnDecisionType.BACKCHANNEL
            and decision.decision is TurnDecisionType.TRUE_INTERRUPT
            for event, decision in zip(events, decisions)
        )
        playback_false_interrupt[name] = sum(
            event.agent_playing
            and event.expected_decision is not TurnDecisionType.TRUE_INTERRUPT
            and decision.decision is TurnDecisionType.TRUE_INTERRUPT
            for event, decision in zip(events, decisions)
        )

        predicted_end_by_turn: dict[str, float] = {}
        for decision in decisions:
            if decision.decision is TurnDecisionType.END_OF_TURN:
                predicted_end_by_turn.setdefault(
                    decision.turn_id, decision.timestamp * 1000
                )
        deltas = [
            predicted_end_by_turn[turn_id] - reference_timestamp
            for turn_id, reference_timestamp in reference_end_by_turn.items()
            if turn_id in predicted_end_by_turn
        ]
        delta_ms[name] = _distribution(deltas)

    return {
        "agreement": {
            "count": agreed,
            "total": total,
            "rate": agreed / total if total else None,
        },
        "false_end": false_end,
        "missed_end": missed_end,
        "missed_interrupt": missed_interrupt,
        "false_interrupt": false_interrupt,
        "backchannel_false_interrupt": backchannel_false_interrupt,
        "playback_false_interrupt": playback_false_interrupt,
        "delta_ms": delta_ms,
    }


def _distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None}
    ordered = sorted(values)
    p95_index = math.ceil(len(ordered) * 0.95) - 1
    return {
        "count": len(ordered),
        "mean": float(mean(ordered)),
        "median": float(median(ordered)),
        "p95": float(ordered[p95_index]),
    }
