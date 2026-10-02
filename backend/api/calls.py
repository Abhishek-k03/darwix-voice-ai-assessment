"""Calls: pack list, web-call tokens with explicit agent dispatch (voice agent + live copilot in the same room),
human-agent join tokens for escalation, simulated calls, and recorded-call evidence."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from livekit import api

from packs import list_packs, load_pack

router = APIRouter(tags=["calls"])

VOICE_AGENT = os.getenv("VOICE_AGENT_NAME", "voice-agent")
COPILOT_AGENT = os.getenv("COPILOT_AGENT_NAME", "call-copilot")
SIM_AGENT = os.getenv("SIM_AGENT_NAME", "sim-caller")
EVIDENCE = Path(__file__).resolve().parents[2] / "evidence" / "calls"


def _keys() -> tuple[str, str]:
    key, secret = os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET")
    if not key or not secret:
        raise HTTPException(503, "LIVEKIT_API_KEY / LIVEKIT_API_SECRET not configured")
    return key, secret


def _token(identity: str, room: str, *, name: str | None = None, attributes: dict | None = None,
           dispatches: list[tuple[str, dict]] | None = None) -> str:
    key, secret = _keys()
    t = (api.AccessToken(key, secret).with_identity(identity).with_name(name or identity)
         .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True)))
    if attributes:
        t = t.with_attributes(attributes)
    if dispatches:
        t = t.with_room_config(api.RoomConfiguration(
            agents=[api.RoomAgentDispatch(agent_name=n, metadata=json.dumps(m)) for n, m in dispatches]))
    return t.to_jwt()


def _frontend() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:3000")


@router.get("/packs")
async def packs():
    return [p.public() for p in list_packs()]


@router.post("/calls")
async def create_call(body: dict | None = None):
    body = body or {}
    pack = load_pack(body.get("pack"))
    room = f"call-{pack.id.replace('_', '-')}-{uuid.uuid4().hex[:6]}"
    call_id = uuid.uuid4().hex[:10]
    meta = {"pack": pack.id, "call_id": call_id, "mode": "web", "customer_id": body.get("customer_id")}
    dispatches = [(VOICE_AGENT, meta)]
    if body.get("copilot", True):
        dispatches.append((COPILOT_AGENT, {**meta, "role": "copilot"}))
    token = _token("customer-web", room, name="Customer", attributes={"role": "customer"}, dispatches=dispatches)
    return {"token": token, "url": os.getenv("LIVEKIT_URL"), "room": room, "call_id": call_id, "pack": pack.public(),
            "copilot_url": f"{_frontend()}/copilot/{room}"}


@router.get("/get-token")
async def get_token(pack: str | None = None):
    """Backwards-compatible with the original frontend contract."""
    return await create_call({"pack": pack})


def human_join(room: str) -> dict:
    identity = f"advisor-{uuid.uuid4().hex[:4]}"
    token = _token(identity, room, name="Licensed advisor", attributes={"role": "advisor"})
    url = os.getenv("LIVEKIT_URL", "")
    return {"identity": identity, "token": token, "url": url,
            "join_url": f"{_frontend()}/agent?{urlencode({'room': room, 'token': token, 'url': url})}"}


@router.post("/calls/{room}/human-token")
async def human_token(room: str):
    return human_join(room)


@router.post("/sim/start")
async def sim_start(body: dict):
    """Creates a room with the voice agent, the simulated caller (persona scenario) and the copilot."""
    pack = load_pack(body.get("pack"))
    scenario = body.get("scenario", "cooperative")
    if not (Path(__file__).resolve().parent.parent / "sim" / "personas" / pack.id / f"{scenario}.yaml").exists():
        raise HTTPException(400, f"no simulated caller for {pack.id}/{scenario}")
    room = f"sim-{pack.id.replace('_', '-')}-{scenario.replace('_', '-')}-{uuid.uuid4().hex[:4]}"
    call_id = uuid.uuid4().hex[:10]
    meta = {"pack": pack.id, "call_id": call_id, "mode": "sim", "scenario": scenario, "customer_id": body.get("customer_id")}
    key, secret = _keys()
    lk = api.LiveKitAPI(os.getenv("LIVEKIT_URL"), key, secret)
    try:
        agents = [(VOICE_AGENT, meta), (SIM_AGENT, {**meta, "role": "caller"})]
        if body.get("copilot", True):
            agents.append((COPILOT_AGENT, {**meta, "role": "copilot"}))
        for name, m in agents:
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=name, room=room, metadata=json.dumps(m)))
    finally:
        await lk.aclose()
    return {"room": room, "call_id": call_id, "scenario": scenario, "copilot_url": f"{_frontend()}/copilot/{room}"}


@router.get("/calls/recorded")
async def recorded():
    out = []
    for p in sorted(EVIDENCE.glob("*/result.json"), reverse=True):
        r = json.loads(p.read_text(encoding="utf-8"))
        out.append({"call_id": r.get("call_id"), "pack": r.get("pack"), "outcome": r.get("outcome"),
                    "grade": r.get("grade"), "scenario": r.get("scenario"), "duration_s": r.get("duration_s"),
                    "dir": p.parent.name})
    return out
