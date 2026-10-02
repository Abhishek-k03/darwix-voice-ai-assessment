"""Grounded answer for the knowledge page: retrieved records -> a short cited answer.

The LLM may only use the numbered sources; citations it makes up are dropped, and with none left (or on any LLM
failure) the answer falls back to the top records' own sentences, so the page never shows an uncited claim.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re

from llm_stream import LLMConfig, build_client, create_completion

logger = logging.getLogger("kb.answer")

TIMEOUT_S = float(os.getenv("KB_ANSWER_TIMEOUT_S", "8"))
CITE = re.compile(r"\[(\d+)\]")
SYSTEM = (
    "You answer questions for a customer-service team using ONLY the numbered sources. "
    "Cite every claim with its source number like [1]. Never add facts, numbers or conditions that are not in a source. "
    "If the sources do not answer the question, reply exactly NO_ANSWER. "
    "Write 1 to 3 short plain-text paragraphs, no markdown or lists, in the language of the question. "
    "Then a line 'FOLLOWUPS:' and up to two short follow-up questions the sources could answer, one per line."
)

_client = None


def _llm():
    global _client
    cfg = LLMConfig.from_env()
    if _client is None:
        _client = build_client(cfg)
    return _client, cfg


def sources(hits: list[dict]) -> list[dict]:
    out = []
    for n, h in enumerate(hits, start=1):
        src = h.get("source") or {}
        path = " › ".join(p for p in (src.get("section"), src.get("uri")) if p)
        out.append({"n": n, "record_id": h["record_id"], "title": h["title"], "path": path or h.get("citation", ""),
                    "snippet": h["content"].strip(), "rel": round(max(0.0, min(1.0, h.get("dense", 0))) * 100),
                    "needs_review": bool(h.get("needs_review"))})
    return out


def parse(text: str, n_sources: int) -> tuple[list[list[dict]], list[str]]:
    """LLM text -> paragraphs of segments [{t, c?}] with valid citations only, plus follow-up questions."""
    body, _, tail = text.partition("FOLLOWUPS:")
    paragraphs = []
    for para in re.split(r"\n\s*\n", body.strip()):
        segs, pos = [], 0
        for m in CITE.finditer(para):
            chunk = para[pos:m.start()].replace("*", "").strip()
            c = int(m.group(1))
            if chunk and 1 <= c <= n_sources:
                segs.append({"t": chunk + " ", "c": c})
            elif chunk:
                segs.append({"t": chunk + " "})
            pos = m.end()
        rest = para[pos:].replace("*", "").strip()
        if rest:
            segs.append({"t": rest})
        if segs:
            paragraphs.append(segs)
    followups = [re.sub(r"^[-•\d.\s]+", "", line).strip() for line in tail.splitlines() if line.strip()][:2]
    return paragraphs, followups


def cited(paragraphs: list[list[dict]]) -> bool:
    return any("c" in s for p in paragraphs for s in p)


def extractive(hits: list[dict], limit: int = 3) -> list[list[dict]]:
    """No LLM: the first sentences of the best records, each cited to its own record."""
    out = []
    for n, h in enumerate(hits[:limit], start=1):
        sentences = re.split(r"(?<=[.!?])\s+", h["content"].strip().replace("\n", " "))
        text = " ".join(sentences[:2])[:320]
        if text:
            out.append([{"t": text + " ", "c": n}])
    return out


async def compose(query: str, hits: list[dict]) -> dict:
    srcs = sources(hits)
    block = "\n\n".join(f"[{s['n']}] {s['title']}\n{s['snippet']}" for s in srcs)
    try:
        client, cfg = _llm()
        resp = await asyncio.wait_for(create_completion(
            client, cfg, temperature=0.1, max_tokens=500,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": f"Sources:\n{block}\n\nQuestion: {query}"}]), TIMEOUT_S)
        text = (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — the page must always answer
        logger.warning("[kb.answer] LLM unavailable, extractive answer: %s", exc)
        return {"paragraphs": extractive(hits), "followups": [], "mode": "extractive"}
    if text.upper().startswith("NO_ANSWER"):
        return {"paragraphs": [], "followups": [], "mode": "no_answer"}
    paragraphs, followups = parse(text, len(srcs))
    if not cited(paragraphs):
        return {"paragraphs": extractive(hits), "followups": [], "mode": "extractive"}
    return {"paragraphs": paragraphs, "followups": followups, "mode": "llm"}
