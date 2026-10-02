"""Copilot event types. All timestamps are epoch milliseconds so stages measured in different processes
(copilot worker, hub, browser) line up on one clock."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field


class _Clock:
    """Wall clock with an offset so text-mode replays/tests can run on virtual time."""
    offset_ms = 0.0
    virtual: float | None = None

    def now(self) -> float:
        return self.virtual if self.virtual is not None else time.time() * 1000 + self.offset_ms


CLOCK = _Clock()


def now_ms() -> float:
    return CLOCK.now()


@dataclass
class Utterance:
    speaker: str                  # "agent" | "customer"
    text: str
    final: bool
    utterance_id: str
    audio_received_at: float      # when the audio frame holding the segment's last word reached the copilot
    asr_at: float                 # when the transcript arrived
    confidence: float = 1.0
    start_s: float = 0.0          # offsets into this speaker's stream
    end_s: float = 0.0

    @property
    def asr_latency_ms(self) -> int:
        return max(0, int(self.asr_at - self.audio_received_at))

    def event(self) -> dict:
        return {"type": "transcript", "utterance_id": self.utterance_id, "speaker": self.speaker, "text": self.text,
                "final": self.final, "confidence": round(self.confidence, 3), "asr_latency_ms": self.asr_latency_ms,
                "audio_received_at": self.audio_received_at, "asr_at": self.asr_at, "start_s": round(self.start_s, 2),
                "end_s": round(self.end_s, 2)}


@dataclass
class Signal:
    type: str                     # e.g. risky_guaranteed, cross_sell_parents, frustration, missed_opportunity
    nudge: str | None             # template key, None = informational only
    confidence: float
    source: str                   # "rules" | "llm"
    speaker: str
    evidence: str
    utterance: Utterance
    detected_at: float = field(default_factory=now_ms)
    extra: dict = field(default_factory=dict)

    def event(self) -> dict:
        return {"type": "signal", "signal": {"type": self.type, "nudge": self.nudge, "confidence": round(self.confidence, 2),
                                             "source": self.source, "speaker": self.speaker, "evidence": self.evidence,
                                             "detected_at": self.detected_at, **self.extra}}


def typed_utterance(msg: dict, seq: int) -> Utterance | None:
    """A customer line the voice agent received as typed text (no audio, so no ASR): final from the start."""
    text = str(msg.get("text", "")).strip()
    if msg.get("role") != "customer" or not msg.get("typed") or not text:
        return None
    t, at = float(msg.get("t") or 0.0), now_ms()
    return Utterance(speaker="customer", text=text, final=True, utterance_id=f"customer-typed-{seq}", audio_received_at=at,
                     asr_at=at, confidence=1.0, start_s=t, end_s=t)


@dataclass
class Nudge:
    key: str
    priority: int
    title: str
    text: str
    confidence: float
    topic: str
    evidence: str
    citation: str | None
    created_at: float
    expires_at: float
    timeline: dict
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = "active"
    count: int = 1
    escalated: bool = False
    reason: str | None = None

    def public(self) -> dict:
        d = asdict(self)
        d["type"] = self.key
        return d
