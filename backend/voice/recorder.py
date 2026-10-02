"""Call recorder: customer + agent audio on a shared wall-clock timeline, transcript with per-turn citations and
latencies, and the call result. Outputs feed the Q1/Q3 evidence and the Q4 replay (stereo: L=agent, R=customer)."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from livekit import rtc

logger = logging.getLogger("voice.recorder")
EVIDENCE = Path(__file__).resolve().parents[2] / "evidence" / "calls"


class CallRecorder:
    def __init__(self, call_id: str, label: str, sample_rate: int = 24000) -> None:
        self.call_id = call_id
        self.sr = sample_rate
        self.t0 = time.monotonic()
        self.wall0 = time.time()
        self.dir = EVIDENCE / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{label}_{call_id}"
        self._agent = bytearray()
        self._customer = bytearray()
        self.turns: list[dict] = []

    def now(self) -> float:
        return round(time.monotonic() - self.t0, 2)

    def _place(self, buf: bytearray, pcm: bytes, max_gap_s: float = 0.05) -> None:
        target = int((time.monotonic() - self.t0) * self.sr) * 2
        if target - len(buf) > max_gap_s * self.sr * 2:
            buf.extend(b"\x00" * (target - len(buf)))
        buf.extend(pcm)

    def agent_frame(self, pcm: bytes) -> None:
        self._place(self._agent, pcm)

    async def capture_customer(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=self.sr, num_channels=1)
        first = True
        async for ev in stream:
            pcm = bytes(ev.frame.data)
            if first:
                self._place(self._customer, pcm)
                first = False
            else:
                self._customer.extend(pcm)

    def add_turn(self, role: str, text: str, **meta) -> None:
        self.turns.append({"t": self.now(), "role": role, "text": text, **meta})

    def finalize(self, result: dict) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        a = np.frombuffer(bytes(self._agent), dtype=np.int16)
        c = np.frombuffer(bytes(self._customer), dtype=np.int16)
        n = max(len(a), len(c))
        if n:
            a2, c2 = np.pad(a, (0, n - len(a))), np.pad(c, (0, n - len(c)))
            sf.write(self.dir / "agent.flac", a2, self.sr)
            sf.write(self.dir / "customer.flac", c2, self.sr)
            mixed = np.clip(a2.astype(np.int32) + c2.astype(np.int32), -32768, 32767).astype(np.int16)
            sf.write(self.dir / "mixed.flac", mixed, self.sr)
            sf.write(self.dir / "stereo.flac", np.stack([a2, c2], axis=1), self.sr)
        result = {**result, "call_id": self.call_id, "started_at": datetime.fromtimestamp(self.wall0).isoformat(timespec="seconds"),
                  "audio_seconds": round(n / self.sr, 1)}
        (self.dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        (self.dir / "transcript.json").write_text(json.dumps(self.turns, indent=2, ensure_ascii=False), encoding="utf-8")
        (self.dir / "transcript.md").write_text(self._markdown(result), encoding="utf-8")
        logger.info("[recorder] saved %s (%.1fs audio)", self.dir, n / self.sr)
        return self.dir

    def _markdown(self, result: dict) -> str:
        lines = [f"# Call {self.call_id} — {result.get('pack')} ({result.get('scenario') or result.get('mode')})", "",
                 f"- outcome: **{result.get('outcome')}** · grade: **{result.get('grade')}** · duration {result.get('duration_s')}s",
                 f"- product: {result.get('product')} · indicative premium: {result.get('premium_inr')}",
                 f"- escalated: {result.get('escalated')} · callback: {result.get('callback')} · lead: {result.get('lead_id')}", "",
                 "| t (s) | speaker | text | KB citations |", "|---|---|---|---|"]
        for t in self.turns:
            cites = ", ".join(t.get("citations") or [])
            lines.append(f"| {t['t']} | {t['role']} | {t['text'].replace('|', '/')} | {cites} |")
        lines += ["", "## Collected fields", "", "```json", json.dumps(result.get("fields", {}), indent=2, ensure_ascii=False), "```"]
        return "\n".join(lines)
