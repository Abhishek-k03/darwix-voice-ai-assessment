"""KB client used by the voice agent and copilot workers.

The KB (embedding model + Chroma + BM25) is served by the FastAPI backend (/kb/search) so there is exactly one
model instance and one versioned index; workers call it over HTTP (~5 ms on localhost). Never raises.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time

import httpx

logger = logging.getLogger("nexus.rag")

_clients: dict[int, httpx.AsyncClient] = {}


def _http() -> httpx.AsyncClient:
    """One client per event loop: on Windows each LiveKit job runs in its own thread + loop."""
    key = id(asyncio.get_running_loop())
    if key not in _clients:
        _clients[key] = httpx.AsyncClient(base_url=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"), timeout=2.0)
    return _clients[key]


_QUESTION = re.compile(
    r"(?:^|[.,;!?]\s*)((?:is|are|does|do|can|will|what|how|which|when|why|where|could|would|may|should"
    r"|ano|paano|magkano|kailan|pwede|apa|apakah|bagaimana|berapa|kapan|bisa|boleh)\b[^.,;!?]*\?)", re.I)


async def search_turn(utterance: str, market: str, k: int = 3) -> dict:
    """The whole turn first (keeps objection context); its question part rescues a miss when an answer padded around
    the question ('myself, my wife and daughter, is maternity covered too?') dilutes it below the relevance gate."""
    focus = question_focus(utterance)
    if focus == utterance:
        return await search(utterance, market, k=k)
    full, part = await asyncio.gather(search(utterance, market, k=k), search(focus, market, k=k))
    return full if full.get("status") == "ok" or part.get("status") != "ok" else part


def question_focus(utterance: str) -> str:
    out = []
    for sentence in re.findall(r"[^.!?]*\?", utterance):
        clause = _QUESTION.findall(sentence)
        out.append(clause[-1] if clause else sentence.strip())
    return " ".join(out) if out else utterance


async def search(query: str, market: str, k: int = 3, doc_types: list[str] | None = None,
                 timeout: float = 0.8) -> dict:
    t0 = time.perf_counter()
    params: dict = {"q": query, "market": market, "k": k}
    if doc_types:
        params["doc_type"] = doc_types
    try:
        resp = await _http().get("/kb/search", params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — KB outage degrades to "no information", never crashes a call
        logger.warning("[rag] KB search failed: %s", exc)
        data = {"status": "error", "hits": [], "llm_context": "NO_RELEVANT_INFO: knowledge base unavailable."}
    data["client_latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return data
