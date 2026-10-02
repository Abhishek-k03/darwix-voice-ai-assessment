"""Business actions from the voice worker -> backend mock CRM (lead + summary, callback, escalation, DNC).
Failures are logged, never raised: a CRM outage must not break a live call."""

from __future__ import annotations

import logging
import os
import time

import httpx

from packs import Pack

from .state import CallState

logger = logging.getLogger("voice.actions")


async def _post(path: str, payload: dict) -> dict | None:
    try:
        async with httpx.AsyncClient(base_url=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"), timeout=3.0) as c:
            r = await c.post(path, json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[actions] POST %s failed: %s", path, exc)
        return None


def summary(state: CallState, pack: Pack) -> dict:
    e = state.eligibility or {}
    return {
        "call_id": state.call_id, "room": state.room, "pack": pack.id, "market": pack.market,
        "duration_s": round(time.time() - state.started_at, 1), "stage": state.stage,
        "outcome": state.outcome or ("qualified" if e.get("eligible") else "incomplete"),
        "grade": e.get("grade"), "product": e.get("product"), "premium_inr": e.get("indicative_premium_inr"),
        "fields": state.known(), "conflicts_resolved": state.resolved_conflicts,
        "open_conflicts": [c.__dict__ for c in state.pending_conflicts], "objections": state.objections,
        "eligibility": e, "callback": state.callback, "escalated": state.escalated, "dnc": state.dnc,
        "disclosed_waiting_period": state.disclosed_waiting_period, "customer": state.customer,
    }


async def escalate(state: CallState, pack: Pack, reason: str) -> dict | None:
    return await _post("/crm/escalations", {"call_id": state.call_id, "room": state.room, "pack": pack.id,
                                            "reason": reason, "summary": summary(state, pack)})


async def schedule_callback(state: CallState, pack: Pack, when: str, reason: str = "advisor follow-up") -> dict | None:
    return await _post("/crm/callbacks", {"call_id": state.call_id, "pack": pack.id, "when_text": when, "reason": reason})


async def mark_dnc(state: CallState, pack: Pack) -> dict | None:
    return await _post("/crm/dnc", {"call_id": state.call_id, "pack": pack.id, "phone": state.customer.get("phone", "")})


async def create_lead(state: CallState, pack: Pack) -> dict | None:
    s = summary(state, pack)
    res = await _post("/crm/leads", {"call_id": state.call_id, "room": state.room, "pack": pack.id, "grade": s["grade"],
                                     "outcome": s["outcome"], "product": s["product"], "premium_inr": s["premium_inr"],
                                     "fields": s["fields"], "summary": s})
    if res:
        state.lead_id = res.get("id")
    return res
