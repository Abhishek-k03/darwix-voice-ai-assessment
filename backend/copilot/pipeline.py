"""Per-call copilot pipeline (transport-agnostic: used by the live LiveKit worker and the offline replay)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import yaml

import rag
from packs import PACKS_DIR, Pack, load_pack

from .events import Utterance, now_ms
from .nudge_engine import Controls, NudgeEngine
from .signals_llm import LLMClassifier
from .signals_rules import RuleDetector

logger = logging.getLogger("copilot.pipeline")
Sink = Callable[[dict], Awaitable[None]]


def load_config(pack: Pack) -> dict:
    own = yaml.safe_load((PACKS_DIR / pack.id / "copilot.yaml").read_text(encoding="utf-8"))
    if not pack.extends:
        return own
    cfg = load_config(load_pack(pack.extends))  # language variant: the base patterns plus its own
    for name, sig in own.get("signals", {}).items():
        base = cfg["signals"].get(name, {})
        cfg["signals"][name] = {**base, **sig, "patterns": base.get("patterns", []) + sig.get("patterns", []),
                                "resolve_patterns": base.get("resolve_patterns", []) + sig.get("resolve_patterns", [])}
        if not cfg["signals"][name]["resolve_patterns"]:
            del cfg["signals"][name]["resolve_patterns"]
    if "lexicon" in own.get("frustration", {}):
        cfg["frustration"] = {**cfg["frustration"], "lexicon": cfg["frustration"]["lexicon"] + own["frustration"]["lexicon"]}
    cfg["nudges"].update(own.get("nudges", {}))
    return cfg


class CopilotPipeline:
    def __init__(self, pack: Pack, sink: Sink, *, controls: Controls | None = None, use_llm: bool = True,
                 metrics_path: Path | None = None) -> None:
        self.pack = pack
        self.cfg = load_config(pack)
        self.rules = RuleDetector(self.cfg)
        self.engine = NudgeEngine(self.cfg["nudges"], controls=controls or Controls())
        self.llm = LLMClassifier() if use_llm else None
        self.sink = sink
        self.history: list[Utterance] = []
        self._metrics = open(metrics_path, "a", encoding="utf-8") if metrics_path else None
        self._tasks: set[asyncio.Task] = set()
        self._tick_task: asyncio.Task | None = None
        self._last: Utterance | None = None

    async def start(self) -> None:
        await self._warm_citations()
        self._tick_task = asyncio.ensure_future(self._tick())

    async def _warm_citations(self) -> None:
        """Pre-resolve KB citations for nudge templates so enrichment costs nothing at call time."""
        async def one(key: str, q: str) -> None:
            res = await rag.search(q, self.pack.market, k=1, timeout=2.0)
            if res.get("status") == "ok" and res.get("hits"):
                h = res["hits"][0]
                self.engine.citations[key] = f"{h['record_id']} · {h['title']}"
        await asyncio.gather(*(one(k, t["kb_query"]) for k, t in self.cfg["nudges"].items() if t.get("kb_query")))

    def metric(self, **kw) -> None:
        if self._metrics:
            self._metrics.write(json.dumps({"at": now_ms(), **kw}, ensure_ascii=False) + "\n")
            self._metrics.flush()

    async def emit(self, events: list[dict]) -> None:
        for e in events:
            if e.get("decision"):
                self.metric(kind="decision", **{k: v for k, v in e.items() if k != "type"})
            if e.get("type") == "nudge":
                n = e["nudge"]
                self.metric(kind="nudge", id=n["id"], key=n["key"], priority=n["priority"], confidence=n["confidence"],
                            timeline=n["timeline"], evidence=n["evidence"])
            await self.sink(e)

    async def on_transcript(self, u: Utterance) -> None:
        await self.sink(u.event())
        self.metric(kind="asr", speaker=u.speaker, final=u.final, asr_latency_ms=u.asr_latency_ms,
                    confidence=round(u.confidence, 3), words=len(u.text.split()), end_s=round(u.end_s, 2))
        if not u.final:
            return
        self.history.append(u)
        self._last = u
        t0 = now_ms()
        signals = self.rules.on_utterance(u)
        t_sig = now_ms()
        events: list[dict] = []
        if self.rules.resolved_topics:
            events += self.engine.resolve(self.rules.resolved_topics, "agent_addressed")
        for s in signals:
            events.append(s.event())
            events += self._consider(s, self._timeline(u, t_sig, "rules", t_sig - t0))
        events += self.engine.expire()
        await self.emit(events)
        if self.llm and self.llm.due(u):
            task = asyncio.ensure_future(self._run_llm(u))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _consider(self, s, timeline: dict) -> list[dict]:
        out = self.engine.consider(s, timeline)
        if s.type == "missed_opportunity" and any(e.get("reason") in ("global_rate_limit", "max_active") for e in out):
            self.rules.retry_missed(s.extra.get("origin", ""), now_ms())
        return out

    async def _run_llm(self, u: Utterance) -> None:
        signals, sentiment, info = await self.llm.classify(self.history, u)
        t_sig = now_ms()
        self.metric(kind="llm", **info)
        if sentiment is not None:
            signals += self.rules.apply_sentiment(u, sentiment)
        events: list[dict] = []
        for s in signals:
            events.append(s.event())
            events += self.engine.consider(s, self._timeline(u, t_sig, "llm", info.get("llm_ms")))
        await self.emit(events)

    @staticmethod
    def _timeline(u: Utterance, t_sig: float, source: str, signal_ms) -> dict:
        return {"audio_received_at": u.audio_received_at, "asr_at": u.asr_at, "signal_at": t_sig, "source": source,
                "signal_ms": round(signal_ms or 0, 2), "asr_confidence": round(u.confidence, 3)}

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            events = self.engine.expire()
            if self._last:
                for s in self.rules.tick(now_ms(), self._last) + self.rules.check_missed(self._last, now_ms()):
                    events += [s.event()] + self._consider(s, self._timeline(self._last, now_ms(), "rules", 0))
            if events:
                await self.emit(events)

    async def aclose(self) -> None:
        if self._tick_task:
            self._tick_task.cancel()
        for t in list(self._tasks):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(t, 3)
        self.metric(kind="summary", decisions=len(self.engine.decisions),
                    emitted=sum(d["decision"] == "emitted" for d in self.engine.decisions))
        if self._metrics:
            self._metrics.close()
