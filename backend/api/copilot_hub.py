"""Q4 delivery hub (pattern adapted from ai-ear ws_server: session-keyed WebSocket fan-out with sent_at stamps).

Producer:   copilot worker -> WS /ws/copilot/ingest?token=...   {"room": ..., "event": {...}}
Consumers:  dashboard      -> WS /ws/copilot/{room}             (snapshot on connect, then live events)
            polling        -> GET /copilot/{room}/nudges | /events
Acks:       dashboard sends {"type":"ack","nudge_id":...,"displayed_at":epoch_ms} -> delivery/display latency logged.
Single-process in-memory state; at 10x scale this becomes Redis pub/sub (see docs/q4_realtime.md).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["copilot"])
logger = logging.getLogger("api.copilot_hub")
LOG_DIR = Path(__file__).resolve().parents[2] / "evidence" / "q4" / "events"


def now_ms() -> float:
    return time.time() * 1000


class Hub:
    def __init__(self) -> None:
        self.subs: dict[str, set[WebSocket]] = defaultdict(set)
        self.history: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.nudges: dict[str, dict[str, dict]] = defaultdict(dict)
        self.last_seen: dict[str, float] = {}

    def _log(self, room: str, record: dict) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / f"{room}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def publish(self, room: str, event: dict) -> None:
        event = {**event, "hub_received_at": now_ms()}
        self.last_seen[room] = time.time()
        self.history[room].append(event)
        if event.get("type") in ("nudge", "nudge_update"):
            n = self.nudges[room].setdefault(event["nudge"]["id"], {})
            n.update(event["nudge"])
        self._log(room, event)
        targets = list(self.subs.get(room, ()))
        if not targets:
            return
        payload = json.dumps({**event, "hub_sent_at": now_ms()}, ensure_ascii=False)
        results = await asyncio.gather(*(ws.send_text(payload) for ws in targets), return_exceptions=True)
        for ws, r in zip(targets, results):
            if isinstance(r, Exception):
                self.subs[room].discard(ws)

    def ack(self, room: str, msg: dict) -> None:
        nid = msg.get("nudge_id")
        n = self.nudges.get(room, {}).get(nid)
        if not n or n.get("displayed_at"):
            return
        n["displayed_at"] = float(msg.get("displayed_at") or now_ms())
        record = {"type": "display_ack", "nudge_id": nid, "displayed_at": n["displayed_at"],
                  "timeline": {**(n.get("timeline") or {}), "displayed_at": n["displayed_at"]}}
        self.history[room].append(record)
        self._log(room, record)


hub = Hub()


@router.websocket("/ws/copilot/ingest")
async def ingest(ws: WebSocket, token: str = ""):
    if token != os.getenv("COPILOT_HUB_TOKEN", "change-me"):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            await hub.publish(msg["room"], msg["event"])
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("ingest closed: %s", exc)


@router.websocket("/ws/copilot/{room}")
async def subscribe(ws: WebSocket, room: str):
    await ws.accept()
    hub.subs[room].add(ws)
    await ws.send_text(json.dumps({"type": "snapshot", "events": list(hub.history[room])[-300:]}, ensure_ascii=False))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "ack":
                hub.ack(room, msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.subs[room].discard(ws)


@router.get("/copilot/rooms")
async def rooms():
    return sorted(({"room": r, "last_seen": t, "nudges": len(hub.nudges.get(r, {}))} for r, t in hub.last_seen.items()),
                  key=lambda x: -x["last_seen"])


@router.get("/copilot/{room}/nudges")
async def nudges(room: str, active: bool = False):
    items = list(hub.nudges.get(room, {}).values())
    if active:
        t = now_ms()
        items = [n for n in items if n.get("status") == "active" and n.get("expires_at", t + 1) > t]
    return sorted(items, key=lambda n: n.get("created_at", 0), reverse=True)


@router.get("/copilot/{room}/events")
async def events(room: str, since: float = 0):
    return [e for e in hub.history.get(room, []) if e.get("hub_received_at", 0) > since]
