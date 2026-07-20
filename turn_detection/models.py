from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TurnDecisionType(str, Enum):
    CONTINUE_SPEAKING = "CONTINUE_SPEAKING"
    END_OF_TURN = "END_OF_TURN"
    TRUE_INTERRUPT = "TRUE_INTERRUPT"
    BACKCHANNEL = "BACKCHANNEL"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class TurnDecision:
    event_id: str
    session_id: str
    turn_id: str
    timestamp: float
    decision: TurnDecisionType
    confidence: float
    reason: str
    vad_state: str
    partial_text: str
    final_text: str
    agent_playing: bool
    detector_name: str
    detector_latency_ms: float
