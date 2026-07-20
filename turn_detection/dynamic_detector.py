from __future__ import annotations

from turn_detection.models import TurnDecision, TurnDecisionType
from turn_detection.replay import ReplayEvent


_BACKCHANNELS = frozenset({"嗯", "嗯嗯", "对", "好", "好的", "是的", "我在听"})
_INTERRUPT_PHRASES = (
    "停",
    "停止",
    "等一下",
    "等等",
    "不对",
    "别说",
    "先别",
    "让我说",
)
_NEGATED_INTERRUPT_PHRASES = (
    "不要停",
    "别停",
    "不用停",
    "不要停止",
    "别停止",
    "不用停止",
)


class DynamicV1Detector:
    name = "dynamic_v1"

    def __init__(self, silence_threshold_ms: float = 300) -> None:
        self.silence_threshold_ms = silence_threshold_ms

    def __call__(self, event: ReplayEvent) -> TurnDecision:
        decision, confidence, reason = self._classify(event)
        return TurnDecision(
            event_id=event.event_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            timestamp=event.timestamp_ms / 1000,
            decision=decision,
            confidence=confidence,
            reason=reason,
            vad_state=event.vad_state,
            partial_text=event.partial_text,
            final_text=event.final_text,
            agent_playing=event.agent_playing,
            detector_name=self.name,
            detector_latency_ms=0.0,
        )

    def _classify(
        self, event: ReplayEvent
    ) -> tuple[TurnDecisionType, float, str]:
        text = (event.final_text or event.partial_text).strip()
        normalized_text = text.strip(" ，。！？!?.,")

        if event.agent_playing:
            if normalized_text in _BACKCHANNELS:
                return TurnDecisionType.BACKCHANNEL, 0.95, "short backchannel"
            if any(phrase in normalized_text for phrase in _NEGATED_INTERRUPT_PHRASES):
                return TurnDecisionType.UNCERTAIN, 0.7, "negated interruption phrase"
            if any(phrase in normalized_text for phrase in _INTERRUPT_PHRASES):
                return TurnDecisionType.TRUE_INTERRUPT, 0.95, "explicit user intent"
            return TurnDecisionType.UNCERTAIN, 0.5, "ambiguous speech during playback"

        if event.vad_state == "speech" and not event.final_text.strip():
            return TurnDecisionType.CONTINUE_SPEAKING, 0.9, "speech is still active"
        if (
            event.final_text.strip()
            and event.vad_state == "silence"
            and event.silence_ms >= self.silence_threshold_ms
        ):
            return (
                TurnDecisionType.END_OF_TURN,
                0.9,
                "final transcript and short silence",
            )
        return TurnDecisionType.UNCERTAIN, 0.5, "insufficient endpoint evidence"
