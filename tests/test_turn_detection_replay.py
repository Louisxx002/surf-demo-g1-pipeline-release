from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from turn_detection.baseline_detector import BaselineDetector
from turn_detection.dynamic_detector import DynamicV1Detector
from turn_detection.metrics import summarize_comparison
from turn_detection.models import TurnDecisionType
from turn_detection.replay import load_timeline, replay_detector


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "turn_detection" / "timeline.jsonl"


def test_loads_and_replays_jsonl_timeline_in_timestamp_order() -> None:
    events = load_timeline(FIXTURE)

    assert [event.event_id for event in events] == [
        "event-001",
        "event-002",
        "event-003",
        "event-004",
        "event-005",
        "event-006",
    ]
    assert events[1].final_text == "今天天气怎么样？"
    assert events[3].agent_playing is True

    decisions = replay_detector(events, BaselineDetector(silence_threshold_ms=600))

    assert [decision.event_id for decision in decisions] == [
        event.event_id for event in events
    ]
    assert all(decision.detector_name == "baseline" for decision in decisions)


def test_rejects_out_of_order_timeline(tmp_path: Path) -> None:
    path = tmp_path / "out-of-order.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"event_id": "late", "timestamp_ms": 20}),
                json.dumps({"event_id": "early", "timestamp_ms": 10}),
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timestamp order"):
        load_timeline(path)


def test_baseline_reproduces_fixed_silence_endpoint() -> None:
    decisions = replay_detector(
        load_timeline(FIXTURE), BaselineDetector(silence_threshold_ms=600)
    )

    assert decisions[1].decision is TurnDecisionType.CONTINUE_SPEAKING
    assert decisions[2].decision is TurnDecisionType.END_OF_TURN


def test_dynamic_v1_emits_candidate_decisions_without_runtime_control() -> None:
    decisions = replay_detector(
        load_timeline(FIXTURE), DynamicV1Detector(silence_threshold_ms=300)
    )

    assert [decision.decision for decision in decisions] == [
        TurnDecisionType.CONTINUE_SPEAKING,
        TurnDecisionType.END_OF_TURN,
        TurnDecisionType.UNCERTAIN,
        TurnDecisionType.BACKCHANNEL,
        TurnDecisionType.TRUE_INTERRUPT,
        TurnDecisionType.UNCERTAIN,
    ]
    assert all(decision.detector_name == "dynamic_v1" for decision in decisions)


@pytest.mark.parametrize("text", ["不要停", "别停", "不用停止", "继续，不要停"])
def test_dynamic_v1_does_not_treat_negated_stop_as_interrupt(text: str) -> None:
    event = load_timeline(FIXTURE)[4]
    event = event.__class__(
        **{**event.__dict__, "partial_text": text, "final_text": text}
    )

    decision = DynamicV1Detector()(event)

    assert decision.decision is not TurnDecisionType.TRUE_INTERRUPT


def test_metrics_summarize_agreement_endpoint_errors_and_delta_ms() -> None:
    events = load_timeline(FIXTURE)
    baseline = replay_detector(events, BaselineDetector(silence_threshold_ms=600))
    dynamic = replay_detector(events, DynamicV1Detector(silence_threshold_ms=300))

    summary = summarize_comparison(
        events, {"baseline": baseline, "dynamic_v1": dynamic}
    )

    assert summary == {
        "agreement": {"count": 1, "total": 6, "rate": pytest.approx(1 / 6)},
        "false_end": {"baseline": 1, "dynamic_v1": 0},
        "missed_end": {"baseline": 1, "dynamic_v1": 0},
        "missed_interrupt": {"baseline": 1, "dynamic_v1": 0},
        "false_interrupt": {"baseline": 0, "dynamic_v1": 0},
        "backchannel_false_interrupt": {"baseline": 0, "dynamic_v1": 0},
        "playback_false_interrupt": {"baseline": 0, "dynamic_v1": 0},
        "delta_ms": {
            "baseline": {
                "count": 0,
                "mean": None,
                "median": None,
                "p95": None,
            },
            "dynamic_v1": {
                "count": 1,
                "mean": 0.0,
                "median": 0.0,
                "p95": 0.0,
            },
        },
    }


def test_cli_compares_baseline_and_dynamic_v1_as_json() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "evaluate_turn_detectors.py"), str(FIXTURE)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["detectors"] == ["baseline", "dynamic_v1"]
    assert payload["event_count"] == 6
    assert payload["metrics"]["false_end"] == {"baseline": 1, "dynamic_v1": 0}
    assert payload["metrics"]["missed_end"] == {"baseline": 1, "dynamic_v1": 0}
