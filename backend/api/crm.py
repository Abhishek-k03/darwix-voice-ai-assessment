"""Mock CRM endpoints (business action for Q1: lead + summary, callback, escalation webhook, DNC)."""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException

import crm
from api.calls import human_join

router = APIRouter(prefix="/crm", tags=["crm"])
logger = logging.getLogger("api.crm")


@router.post("/leads")
async def create_lead(body: dict):
    return crm.new_lead({k: body.get(k) for k in ("call_id", "room", "pack", "grade", "outcome", "product",
                                                  "premium_inr", "fields", "summary")})


@router.get("/leads")
async def leads(limit: int = 50):
    return crm.rows("leads", limit)


@router.post("/callbacks")
async def create_callback(body: dict):
    return crm.new_callback({k: body.get(k) for k in ("call_id", "pack", "when_text", "reason")})


@router.get("/callbacks")
async def callbacks(limit: int = 50):
    return crm.rows("callbacks", limit)


@router.post("/escalations")
async def create_escalation(body: dict):
    join = human_join(body.get("room") or "") if body.get("room") else None
    webhook_status = "not_configured"
    url = os.getenv("ESCALATION_WEBHOOK_URL")
    if url:
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.post(url, json={**body, "human_join": join})
            webhook_status = f"http_{r.status_code}"
        except Exception as exc:  # noqa: BLE001
            webhook_status = f"error: {exc}"
            logger.warning("escalation webhook failed: %s", exc)
    row = crm.new_escalation({"call_id": body.get("call_id"), "room": body.get("room"), "pack": body.get("pack"),
                              "reason": body.get("reason"), "summary": body.get("summary"), "webhook_status": webhook_status})
    return {**row, "human_join": join}


@router.get("/escalations")
async def escalations(limit: int = 50):
    return crm.rows("escalations", limit)


@router.post("/dnc")
async def dnc(body: dict):
    return crm.add_dnc({k: body.get(k) for k in ("phone", "call_id", "pack")})


@router.get("/customers/{cid}")
async def customer(cid: str):
    c = crm.customer(cid)
    if not c:
        raise HTTPException(404, "unknown customer")
    return c
