"""Participant roles shared by the voice agent, copilot and sim caller (all in one LiveKit room).

Agent participants get LiveKit-assigned identities, so roles travel as participant attributes:
customer (web user / SIP caller / sim caller), voice_agent, advisor (human escalation), copilot.
"""

from __future__ import annotations

import asyncio

from livekit import rtc

KIND_STANDARD, KIND_SIP, KIND_AGENT = 0, 3, 4


def role_of(p: rtc.Participant) -> str:
    role = (p.attributes or {}).get("role")
    if role:
        return role
    if p.kind == KIND_SIP:
        return "customer"
    if p.identity.startswith("advisor-"):
        return "advisor"
    return "customer" if p.kind == KIND_STANDARD else "unknown"


async def wait_for_role(room: rtc.Room, roles: set[str], timeout: float | None = None) -> rtc.RemoteParticipant:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    def _check(p: rtc.RemoteParticipant, *_a) -> None:
        if not fut.done() and role_of(p) in roles:
            fut.set_result(p)

    for p in room.remote_participants.values():
        _check(p)
    room.on("participant_connected", _check)
    room.on("participant_attributes_changed", lambda _changed, p: _check(p))
    try:
        return await asyncio.wait_for(fut, timeout)
    finally:
        room.off("participant_connected", _check)
