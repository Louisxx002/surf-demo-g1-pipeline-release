from __future__ import annotations

from turn_detection.models import TurnDecision, TurnDecisionType
from turn_detection.replay import ReplayEvent


class BaselineDetector:
    name = "baseline"

    def __init__(self, silence_threshold_ms: float = 600) -> None:
        self.silence_threshold_ms = silence_threshold_ms

    def __call__(self, event: ReplayEvent) -> TurnDecision:
        ended = (
            event.vad_state == "silence"
            and event.silence_ms >= self.silence_threshold_ms
        )
        decision = (
            TurnDecisionType.END_OF_TURN
            if ended
            else TurnDecisionType.CONTINUE_SPEAKING
        )
        return TurnDecision(
            event_id=event.event_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            timestamp=event.timestamp_ms / 1000,
            decision=decision,
            confidence=1.0,
            reason=(
                f"silence reached {self.silence_threshold_ms:g} ms threshold"
                if ended
                else f"silence below {self.silence_threshold_ms:g} ms threshold"
            ),
            vad_state=event.vad_state,
            partial_text=event.partial_text,
            final_text=event.final_text,
            agent_playing=event.agent_playing,
            detector_name=self.name,
            detector_latency_ms=0.0,
        )
