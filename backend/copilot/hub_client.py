"""Persistent WebSocket producer to the backend hub; buffers while reconnecting, never blocks the pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

import websockets

from .events import now_ms

logger = logging.getLogger("copilot.hub")


class HubClient:
    def __init__(self, room: str, url: str | None = None, token: str | None = None, max_buffer: int = 2000) -> None:
        base = (url or os.getenv("BACKEND_URL", "http://127.0.0.1:8000")).replace("http", "ws", 1)
        self.url = f"{base}/ws/copilot/ingest?token={token or os.getenv('COPILOT_HUB_TOKEN', 'change-me')}"
        self.room = room
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_buffer)
        self._task: asyncio.Task | None = None
        self.sent = 0

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def send(self, event: dict) -> None:
        if event.get("type") == "nudge":
            event["nudge"]["timeline"]["sent_at"] = now_ms()
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("[hub] buffer full, dropping %s", event.get("type"))

    async def _run(self) -> None:
        pending: dict | None = None
        while True:
            try:
                async with websockets.connect(self.url, open_timeout=5) as ws:
                    logger.info("[hub] connected")
                    while True:
                        event = pending or await self.queue.get()
                        pending = event
                        await ws.send(json.dumps({"room": self.room, "event": event}, ensure_ascii=False, default=str))
                        pending = None
                        self.sent += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hub] disconnected (%s); retrying", exc)
                await asyncio.sleep(1.0)

    async def aclose(self, drain_s: float = 2.0) -> None:
        deadline = asyncio.get_event_loop().time() + drain_s
        while not self.queue.empty() and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
