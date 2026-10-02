"""Nudge controls: turns signals into a small number of useful, timely nudges.

Every candidate passes, in order:
  confidence threshold (per source) -> ASR-confidence / length gate (noisy audio) -> repetition cap
  -> per-key cooldown -> topic grouping (merge into the active card) -> global rate limit for coaching nudges
     (P1 compliance alerts bypass it and don't consume it)
  -> max active cards (a new card displaces a lower-priority one; P1 is never capped)
Active nudges expire (TTL) or auto-resolve when the agent addresses them. Every decision is logged with a reason —
that log is the basis of the false-positive analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import Nudge, Signal, now_ms


@dataclass
class Controls:
    min_conf_rules: float = 0.6
    min_conf_llm: float = 0.75
    min_asr_conf: float = 0.6
    min_words: int = 3
    cooldown_s: float = 60
    global_gap_s: float = 8
    max_active: int = 3
    max_repeats: int = 2
    enabled: bool = True          # False = ablation baseline: every signal becomes a nudge


@dataclass
class NudgeEngine:
    templates: dict
    citations: dict = field(default_factory=dict)
    controls: Controls = field(default_factory=Controls)
    active: dict[str, Nudge] = field(default_factory=dict)       # nudge_id -> nudge
    last_by_key: dict[str, float] = field(default_factory=dict)
    count_by_key: dict[str, int] = field(default_factory=dict)
    last_emit: float = 0.0
    decisions: list[dict] = field(default_factory=list)

    def _log(self, decision: str, signal: Signal | None, reason: str, **kw) -> dict:
        d = {"type": "suppressed" if decision == "suppressed" else decision, "decision": decision, "reason": reason,
             "signal_type": signal.type if signal else None, "nudge_key": signal.nudge if signal else kw.get("key"),
             "source": signal.source if signal else None, "confidence": signal.confidence if signal else None,
             "evidence": signal.evidence if signal else None, "at": now_ms(), **kw}
        self.decisions.append(d)
        return d

    def expire(self) -> list[dict]:
        t = now_ms()
        events = []
        for nid, n in list(self.active.items()):
            if n.expires_at <= t:
                n.status, n.reason = "expired", "ttl"
                del self.active[nid]
                events.append({"type": "nudge_update", "nudge": {"id": nid, "status": "expired", "reason": "ttl"}})
        return events

    def resolve(self, keys: list[str], why: str) -> list[dict]:
        events = []
        for nid, n in list(self.active.items()):
            if n.key in keys:
                n.status, n.reason = "resolved", why
                del self.active[nid]
                events.append({"type": "nudge_update", "nudge": {"id": nid, "status": "resolved", "reason": why}})
        return events

    def consider(self, s: Signal, timeline: dict) -> list[dict]:
        """Returns hub events (nudge / nudge_update / suppressed)."""
        tpl = self.templates.get(s.nudge or "")
        if not tpl:
            return [self._log("suppressed", s, "informational_only")]
        c, u = self.controls, s.utterance
        t = now_ms()
        if c.enabled:
            p1 = tpl["priority"] == 1
            min_conf = c.min_conf_llm if s.source == "llm" else c.min_conf_rules
            if s.confidence < min_conf:
                return [self._log("suppressed", s, "low_confidence")]
            if s.extra.get("noisy_context"):   # "disclosure missing" inferred from garbled agent audio
                return [self._log("suppressed", s, "noisy_agent_audio")]
            if not p1 and u.confidence < c.min_asr_conf:
                return [self._log("suppressed", s, "low_asr_confidence", asr_confidence=u.confidence)]
            if s.speaker == "customer" and s.type not in ("missed_opportunity", "frustration") and len(u.text.split()) < c.min_words:
                return [self._log("suppressed", s, "utterance_too_short")]
            if self.count_by_key.get(s.nudge, 0) >= c.max_repeats:
                return [self._log("suppressed", s, "repeat_cap")]
            last = self.last_by_key.get(s.nudge)
            if last and t - last < c.cooldown_s * 1000:
                same = next((n for n in self.active.values() if n.key == s.nudge), None)
                if same:
                    same.expires_at = t + tpl.get("ttl_s", 45) * 1000
                    return [self._log("suppressed", s, "duplicate_active_refreshed")]
                return [self._log("suppressed", s, "cooldown")]
            grouped = None if p1 else next((n for n in self.active.values() if n.topic == tpl.get("topic")
                                            and n.key != s.nudge and n.priority <= tpl["priority"]), None)
            if grouped:
                grouped.evidence = f"{grouped.evidence} | {s.evidence}"[:240]
                grouped.expires_at = t + tpl.get("ttl_s", 45) * 1000
                return [self._log("suppressed", s, "grouped_into_active", into=grouped.id),
                        {"type": "nudge_update", "nudge": {"id": grouped.id, "evidence": grouped.evidence,
                                                           "expires_at": grouped.expires_at}}]
            if not p1 and t - self.last_emit < c.global_gap_s * 1000:
                return [self._log("suppressed", s, "global_rate_limit")]
            events: list[dict] = []
            for n in list(self.active.values()):   # a higher-priority card on the same topic replaces the older one
                if n.topic == tpl.get("topic") and n.priority > tpl["priority"]:
                    n.status, n.reason = "superseded", f"escalated_to_{s.nudge}"
                    del self.active[n.id]
                    events.append({"type": "nudge_update", "nudge": {"id": n.id, "status": "superseded", "reason": n.reason}})
            if len(self.active) >= c.max_active:
                worst = max(self.active.values(), key=lambda n: (n.priority, -n.created_at))
                if worst.priority > tpl["priority"]:
                    worst.status, worst.reason = "superseded", "higher_priority"
                    del self.active[worst.id]
                    events.append({"type": "nudge_update", "nudge": {"id": worst.id, "status": "superseded", "reason": "higher_priority"}})
                elif not p1:  # distinct compliance violations are never hidden by the cap
                    return [self._log("suppressed", s, "max_active")]
        else:
            events = []

        repeat = self.count_by_key.get(s.nudge, 0)
        text = tpl["text"].format(what=s.extra.get("what", "something"))
        n = Nudge(key=s.nudge, priority=tpl["priority"], title=("Reminder: " if repeat else "") + tpl["title"], text=text,
                  confidence=round(s.confidence, 2), topic=tpl.get("topic", ""), evidence=s.evidence,
                  citation=self.citations.get(s.nudge), created_at=t, expires_at=t + tpl.get("ttl_s", 45) * 1000,
                  timeline={**timeline, "nudge_at": now_ms()}, escalated=bool(repeat), count=repeat + 1)
        self.active[n.id] = n
        self.last_by_key[s.nudge] = t
        self.count_by_key[s.nudge] = repeat + 1
        if tpl["priority"] > 1:  # compliance alerts don't consume the coaching-nudge rate budget
            self.last_emit = t
        self._log("emitted", s, "passed_controls", nudge_id=n.id)
        events.append({"type": "nudge", "nudge": n.public()})
        return events
