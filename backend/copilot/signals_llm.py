"""Tier-2 signals: fast small LLM over a sliding window of the conversation (JSON mode, debounced, hard timeout).

Hallucination guard: a signal is kept only if its evidence quote appears (fuzzy >= 85) in the window's text.
On timeout/error it returns nothing — tier-1 rules keep working.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

from rapidfuzz import fuzz

from llm_stream import LLMConfig, build_client, create_completion

from .events import Signal, Utterance, now_ms

logger = logging.getLogger("copilot.llm")

TYPES = {"frustration": "frustration", "buying_signal": "buying_signal", "payment_difficulty": "payment_difficulty",
         "cross_sell": None, "callback_need": "callback_need", "human_request": "human_request",
         "risky_statement": "guaranteed_claim", "compliance_gap": "waiting_period_before_quote"}
# An LLM signal of these types must also contain words that fit it (en / tl / id): the quote is real, the reading may
# not be ("No callback for now?" is not a human request; "Maybe 5 or 6,000" is not a buying signal).
GATES = {
    "human_request": re.compile(r"person|human|agent|advis[oe]r|manager|supervisor|someone|somebody|real|operator|"
                                r"tao|ahente|tauhan|petugas|orang|manusia|langsung|इंसान|व्यक्ति|मैनेजर|एजेंट|सलाहकार|असली", re.I),
    "buying_signal": re.compile(r"buy|apply|sign|start|proceed|go ahead|purchase|documents?|interested|take it|let'?s do|"
                                r"bilhin|kukunin|mag-?apply|beli|daftar|ambil|lanjut|ले लू|खरीद|आवेदन|दस्तावेज़|शुरू|दिलचस्पी", re.I),
}

SYSTEM = (
    "You monitor a live sales/service phone call and flag signals that should change what the human agent does next. "
    "Reply ONLY with JSON: {\"signals\":[{\"type\":...,\"confidence\":0-1,\"evidence\":\"exact quote from the transcript\","
    "\"speaker\":\"customer|agent\"}],\"sentiment\":-1..1,\"topic\":\"short label\"}.\n"
    f"Allowed types: {', '.join(TYPES)}.\n"
    "- Only flag what the LATEST turns clearly show. Prefer returning no signals over guessing.\n"
    "- evidence must be copied verbatim from the transcript.\n"
    "- sentiment is the customer's current mood. Small talk, hesitation and filler words are NOT frustration.\n"
)


class LLMClassifier:
    def __init__(self, min_gap_s: float = 4.0, window: int = 8, timeout_s: float = 2.5) -> None:
        cfg = LLMConfig.from_env("FAST_")
        self.enabled = bool(cfg.api_key) and os.getenv("COPILOT_LLM", "on") != "off"
        self.client = build_client(cfg) if self.enabled else None
        self.cfg = cfg
        self.min_gap_s, self.window, self.timeout_s = min_gap_s, window, timeout_s
        self._last = 0.0
        self._busy = False

    def due(self, u: Utterance) -> bool:
        return (self.enabled and not self._busy and u.speaker == "customer" and len(u.text.split()) >= 3
                and time.monotonic() - self._last >= self.min_gap_s)

    async def classify(self, history: list[Utterance], latest: Utterance) -> tuple[list[Signal], float | None, dict]:
        self._busy, self._last = True, time.monotonic()
        t0 = now_ms()
        window = history[-self.window:]
        convo = "\n".join(f"{u.speaker.upper()}: {u.text}" for u in window)
        try:
            resp = await asyncio.wait_for(create_completion(
                self.client, self.cfg, temperature=0, max_tokens=250, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": convo}]), self.timeout_s)
            data = json.loads(resp.choices[0].message.content or "{}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[copilot-llm] skipped: %s", exc)
            return [], None, {"llm_ms": round(now_ms() - t0), "error": str(exc)}
        finally:
            self._busy = False
        out: list[Signal] = []
        dropped = gated = 0
        text = convo.lower()
        for s in data.get("signals") or []:
            typ, ev = s.get("type"), str(s.get("evidence") or "")
            if typ not in TYPES or not ev or fuzz.partial_ratio(ev.lower(), text) < 85:
                dropped += 1
                continue
            if typ in GATES and not GATES[typ].search(ev):
                gated += 1
                continue
            nudge = TYPES[typ]
            if typ == "cross_sell":
                nudge = "cross_sell_parents" if any(w in ev.lower() for w in ("parent", "mother", "father", "in-law", "माता", "पिता", "मम्मी", "पापा", "माँ", "सास", "ससुर")) else "cross_sell_family"
            out.append(Signal(type=typ, nudge=nudge, confidence=float(s.get("confidence") or 0.0), source="llm",
                              speaker=s.get("speaker") or "customer", evidence=ev, utterance=latest))
        sentiment = data.get("sentiment")
        return out, float(sentiment) if isinstance(sentiment, (int, float)) else None, {
            "llm_ms": round(now_ms() - t0), "dropped_unverified": dropped, "dropped_gate": gated, "topic": data.get("topic")}
