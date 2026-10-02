"""Tier-1 signals: deterministic, sub-millisecond, per final transcript segment.

- compliance state machine: quote without prior waiting-period disclosure; no recording disclosure by the deadline
- risky agent statements (guaranteed claims, "no waiting period", asking for OTP)
- customer opportunities with missed-opportunity escalation (not addressed within N agent turns / T seconds)
- buying / payment difficulty / callback / human request / pre-existing mention
- frustration EMA from lexicon hits + repetition of earlier customer content (+ LLM sentiment when available)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .events import Signal, Utterance


@dataclass
class _Opportunity:
    signal_type: str
    what: str
    at_ms: float
    agent_turns: int = 0
    resolve: list[re.Pattern] = field(default_factory=list)
    escalated: bool = False
    retry_at: float = 0.0


class RuleDetector:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.rules = {k: {**v, "rx": [re.compile(p, re.I) for p in v["patterns"]],
                          "resolve_rx": [re.compile(p, re.I) for p in v.get("resolve_patterns", [])]}
                      for k, v in cfg["signals"].items()}
        fr = cfg.get("frustration", {})
        self.frus_rx = [re.compile(p, re.I) for p in fr.get("lexicon", [])]
        self.frus_threshold = fr.get("threshold", 0.45)
        self.frus_alpha = fr.get("ema_alpha", 0.5)
        mo = cfg.get("missed_opportunity", {})
        self.mo_turns, self.mo_seconds = mo.get("agent_turns", 2), mo.get("seconds", 25)
        self.recording_deadline_ms = cfg.get("compliance", {}).get("recording_deadline_s", 30) * 1000
        self.waiting_disclosed = False
        self.recording_disclosed = False
        self.recording_flagged = False
        self.first_agent_ms: float | None = None
        self.opportunities: list[_Opportunity] = []
        self._prev_speaker: str | None = None
        self.agent_conf: list[tuple[float, float]] = []
        self.customer_history: list[str] = []
        self.agent_history: list[str] = []
        self.frustration = 0.0
        self.resolved_topics: list[str] = []   # nudge keys the pipeline should auto-resolve

    def _match(self, key: str, text: str) -> str | None:
        r = self.rules.get(key)
        if not r:
            return None
        for rx in r["rx"]:
            m = rx.search(text)
            if m:
                return m.group(0)
        return None

    def _sig(self, u: Utterance, type_: str, evidence: str, confidence: float | None = None, nudge: str | None = None, **extra) -> Signal:
        r = self.rules.get(type_, {})
        return Signal(type=type_, nudge=nudge if nudge is not None else r.get("nudge"),
                      confidence=confidence if confidence is not None else r.get("confidence", 0.8),
                      source="rules", speaker=u.speaker, evidence=evidence, utterance=u, extra=extra)

    def on_utterance(self, u: Utterance) -> list[Signal]:
        out: list[Signal] = []
        text = u.text
        self.resolved_topics = []
        if u.speaker == "agent":
            out += self._agent(u, text)
        else:
            out += self._customer(u, text)
        out += self._check_missed(u, u.audio_received_at)
        self._prev_speaker = u.speaker
        return out

    def check_missed(self, u: Utterance, now: float) -> list[Signal]:
        return self._check_missed(u, now)

    def retry_missed(self, origin: str, now: float, after_ms: float = 9000) -> None:
        """The nudge was held back (rate limit / card limit): raise it again shortly instead of losing it."""
        for o in self.opportunities:
            if o.signal_type == origin and o.escalated:
                o.escalated, o.retry_at = False, now + after_ms

    def tick(self, now_ms: float, u: Utterance | None = None) -> list[Signal]:
        """Time-based checks (recording deadline); called on every utterance and periodically."""
        if (not self.recording_disclosed and not self.recording_flagged and self.first_agent_ms is not None
                and now_ms - self.first_agent_ms > self.recording_deadline_ms and u is not None):
            self.recording_flagged = True
            return [self._sig(u, "recording_missing", "no recording disclosure in the first "
                              f"{self.recording_deadline_ms // 1000}s", 0.85, nudge="recording_missing",
                              noisy_context=self._noisy_agent(now_ms))]
        return []

    def _noisy_agent(self, now: float, window_ms: float = 30000, floor: float = 0.82) -> bool:
        """Absence-based compliance flags ("disclosure missing") are unreliable when the agent's recent audio was garbled."""
        recent = [c for t, c in self.agent_conf if now - t <= window_ms]
        return bool(recent) and min(recent) < floor

    def _agent(self, u: Utterance, text: str) -> list[Signal]:
        out: list[Signal] = []
        self.agent_conf.append((u.audio_received_at, u.confidence))
        if self.first_agent_ms is None:
            self.first_agent_ms = u.audio_received_at
        if self._match("recording_disclosed", text):
            self.recording_disclosed = True
            self.resolved_topics.append("recording_missing")
        if self._match("waiting_disclosed", text):
            self.waiting_disclosed = True
            self.resolved_topics += ["waiting_period_before_quote", "no_waiting_claim"]
        q = self._match("quote", text)
        if q and not self.waiting_disclosed:
            out.append(self._sig(u, "compliance_gap", q, 0.85, nudge="waiting_period_before_quote",
                                 noisy_context=self._noisy_agent(u.audio_received_at)))
        for key, r in self.rules.items():  # any agent-side rule with a nudge = risky statement
            if r.get("speaker") == "agent" and r.get("nudge"):
                ev = self._match(key, text)
                if ev:
                    out.append(self._sig(u, key, ev))
        for opp in self.opportunities:
            if any(rx.search(text) for rx in opp.resolve):
                self.resolved_topics += [self.rules[opp.signal_type]["nudge"], "missed_opportunity"]
                opp.agent_turns = -999
            elif self._prev_speaker != "agent":      # ASR splits one agent turn into several finals: count it once
                opp.agent_turns += 1
        self.opportunities = [o for o in self.opportunities if o.agent_turns >= 0]
        out += self.tick(u.audio_received_at, u)
        self.agent_history.append(text)
        return out

    def _customer(self, u: Utterance, text: str) -> list[Signal]:
        out: list[Signal] = []
        for key, r in self.rules.items():
            if r.get("speaker") != "customer":
                continue
            ev = self._match(key, text)
            if not ev:
                continue
            if r.get("opportunity") and any(rx.search(a) for rx in r["resolve_rx"] for a in self.agent_history):
                continue  # the agent already covered it — not an opportunity anymore
            out.append(self._sig(u, key, ev))
            if r.get("opportunity") and not any(o.signal_type == key for o in self.opportunities):
                self.opportunities.append(_Opportunity(key, ev, u.audio_received_at, resolve=r["resolve_rx"]))
        out += self._frustration(u, text)
        self.customer_history.append(text)
        return out

    def _frustration(self, u: Utterance, text: str, llm_sentiment: float | None = None) -> list[Signal]:
        hits = [m.group(0) for rx in self.frus_rx for m in [rx.search(text)] if m]
        repeat = any(len(text) > 15 and fuzz.token_set_ratio(text, prev) > 85 for prev in self.customer_history[-5:])
        score = min(1.0, 0.5 * len(hits) + (0.4 if repeat else 0.0) + (max(0.0, -llm_sentiment) * 0.6 if llm_sentiment else 0.0))
        prev = self.frustration
        self.frustration = self.frus_alpha * score + (1 - self.frus_alpha) * self.frustration
        if self.frustration >= self.frus_threshold and self.frustration > prev:
            evidence = hits[0] if hits else ("repeated earlier statement" if repeat else "negative sentiment")
            return [self._sig(u, "frustration", evidence, round(min(1.0, 0.5 + self.frustration / 2), 2), nudge="frustration",
                              level=round(self.frustration, 2))]
        return []

    def apply_sentiment(self, u: Utterance, sentiment: float) -> list[Signal]:
        """LLM sentiment feeds the same EMA (without double-counting lexicon/repetition)."""
        if sentiment > -0.3:
            return []
        return self._frustration(u, "", llm_sentiment=sentiment)

    def _check_missed(self, u: Utterance, now: float) -> list[Signal]:
        out = []
        for o in self.opportunities:
            if o.escalated or now < o.retry_at:
                continue
            if o.agent_turns >= self.mo_turns or (now - o.at_ms) / 1000 >= self.mo_seconds:
                o.escalated = True
                out.append(self._sig(u, "missed_opportunity", o.what, 0.8, nudge="missed_opportunity",
                                     what=o.what, origin=o.signal_type))
        return out
