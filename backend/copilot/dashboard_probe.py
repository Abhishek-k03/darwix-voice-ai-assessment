"""Headless dashboard: subscribes to a room's copilot feed and acks every nudge the moment it arrives (for the
display-latency stats when no browser is open). It measures hub -> client delivery, not browser rendering.

  uv run python -m copilot.dashboard_probe <room> [--seconds 180]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import websockets


async def run(room: str, seconds: float, base: str) -> None:
    seen = 0
    async with websockets.connect(f"{base}/ws/copilot/{room}") as ws:
        end = time.time() + seconds
        while time.time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
            except asyncio.TimeoutError:
                continue
            events = msg.get("events", []) if msg.get("type") == "snapshot" else [msg]
            for e in events:
                if e.get("type") == "nudge":
                    seen += 1
                    await ws.send(json.dumps({"type": "ack", "nudge_id": e["nudge"]["id"], "displayed_at": time.time() * 1000}))
    print(f"acked {seen} nudges in {room}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("room")
    ap.add_argument("--seconds", type=float, default=180)
    ap.add_argument("--base", default=os.getenv("WS_BACKEND", "ws://localhost:8000"))
    a = ap.parse_args()
    asyncio.run(run(a.room, a.seconds, a.base))


if __name__ == "__main__":
    main()
