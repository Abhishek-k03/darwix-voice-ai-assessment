"""KB service: hybrid search with citations, record lookup, build manifest."""

from __future__ import annotations

import asyncio
import json
import threading
import time

from fastapi import APIRouter, HTTPException, Query

from kb import answer as kb_answer
from kb.retriever import KB_DIR, Retriever

router = APIRouter(prefix="/kb", tags=["kb"])
_retriever: Retriever | None = None
_lock = threading.Lock()


def retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        with _lock:
            if _retriever is None:
                _retriever = Retriever()
    return _retriever


def reload() -> None:
    global _retriever
    with _lock:
        _retriever = Retriever()


@router.get("/search")
async def search(q: str, market: str = "in_health", k: int = 3, doc_type: list[str] | None = Query(None)):
    res = await asyncio.to_thread(retriever().search, q, market, k, doc_type)
    out = res.to_dict()
    out["llm_context"] = res.for_llm()
    return out


@router.post("/answer")
async def answer(body: dict):
    """Retrieve, then compose a short answer that cites only the retrieved records (see kb/answer.py)."""
    q = str(body.get("q", "")).strip()
    if not q:
        raise HTTPException(400, "q is required")
    t0 = time.perf_counter()
    res = await asyncio.to_thread(retriever().search, q, body.get("market", "in_health"), int(body.get("k", 4)),
                                  body.get("doc_types") or None)
    hits = [h.to_dict() for h in res.hits]
    base = {"query": q, "market": res.market, "kb_version": res.kb_version, "search_ms": round(res.latency_ms, 1)}
    if res.status != "ok":
        return {**base, "status": "no_match", "answer": None, "sources": [], "followups": []}
    out = await kb_answer.compose(q, hits)
    if not out["paragraphs"]:
        return {**base, "status": "no_match", "answer": None, "sources": [], "followups": []}
    return {**base, "status": "ok", "mode": out["mode"], "answer": out["paragraphs"], "sources": kb_answer.sources(hits),
            "followups": out["followups"], "total_ms": round((time.perf_counter() - t0) * 1000, 1)}


@router.get("/records/{record_id}")
async def record(record_id: str):
    r = retriever().by_id.get(record_id)
    if not r:
        raise HTTPException(404, "record not found or not active")
    return r.model_dump(mode="json")


@router.get("/manifest")
async def manifest():
    m = json.loads((KB_DIR / "manifest.json").read_text(encoding="utf-8"))
    rep = json.loads((KB_DIR / "build_report.json").read_text(encoding="utf-8"))
    return {"kb_version": m["kb_version"], "built_at": m["built_at"], "embedding_model": m.get("embedding_model"),
            "records_active": rep["records_active"], "by_market": rep["by_market"], "by_doc_type": rep["by_doc_type"],
            "issues": rep["issues"], "conflicts": rep["conflicts"]}


@router.post("/reload")
async def reload_index():
    await asyncio.to_thread(reload)
    return {"kb_version": retriever().kb_version}
