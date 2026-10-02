"""Replay a call through the live copilot pipeline.

audio mode (default): a recorded/scripted call (stereo L=agent, R=customer, or --agent/--customer mono files) is
  streamed at real-time speed in fixed chunks into per-speaker streaming STT -> signals -> nudges -> hub.
  This is the "recording replayed at real-time speed in chunks" path; latency numbers come from here.
text mode (--text): the script's lines are fed as final transcripts on a virtual clock (no ASR) — deterministic,
  used for logic tests and the controls on/off ablation.

  uv run python -m copilot.replay ../evidence/q4/scripted/missed_cross_sell/stereo.wav --pack in_health
  uv run python -m copilot.replay sim/scripts/in_health/missed_cross_sell.yaml --text --controls off
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml
from dotenv import find_dotenv, load_dotenv

from packs import load_pack

from .events import CLOCK, Utterance, now_ms
from .nudge_engine import Controls
from .pipeline import CopilotPipeline

load_dotenv(find_dotenv())
ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "evidence" / "q4" / "replays"
SR = 16000
WORDS_PER_S = 2.6


def _load_audio(stereo: Path | None, agent: Path | None, customer: Path | None) -> tuple[np.ndarray, np.ndarray]:
    if stereo:
        data, sr = sf.read(stereo, dtype="int16", always_2d=True)
        a, c = data[:, 0], data[:, 1]
    else:
        a, sr = sf.read(agent, dtype="int16")
        c, sr2 = sf.read(customer, dtype="int16")
        assert sr == sr2
    if sr != SR:
        idx = np.arange(0, len(a), sr / SR)
        a = np.interp(idx, np.arange(len(a)), a).astype(np.int16)
        c = np.interp(idx, np.arange(len(c)), c).astype(np.int16)
    n = max(len(a), len(c))
    return np.pad(a, (0, n - len(a))), np.pad(c, (0, n - len(c)))


async def replay_audio(audio_path: Path | None, pack_id: str, *, agent: Path | None = None, customer: Path | None = None,
                       chunk_ms: int = 100, speed: float = 1.0, use_llm: bool = True, controls_on: bool = True,
                       hub: bool = True, room: str | None = None) -> Path:
    import aiohttp
    from livekit import rtc

    from stt_provider import build_stt

    from .hub_client import HubClient
    from .stt_stream import SpeakerTranscriber

    pack = load_pack(pack_id)
    label = (audio_path.parent.name if audio_path else "replay")
    room = room or f"replay-{label}-{uuid.uuid4().hex[:4]}"
    out = RUNS / room
    out.mkdir(parents=True, exist_ok=True)
    a, c = _load_audio(audio_path, agent, customer)
    events_f = open(out / "events.jsonl", "w", encoding="utf-8")
    hub_client = HubClient(room) if hub else None
    if hub_client:
        hub_client.start()

    async def sink(e: dict) -> None:
        events_f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
        if hub_client:
            await hub_client.send(e)

    pipeline = CopilotPipeline(pack, sink, controls=Controls(enabled=controls_on), use_llm=use_llm,
                               metrics_path=out / "metrics.jsonl")
    await pipeline.start()
    async with aiohttp.ClientSession() as http:
        trs = {spk: SpeakerTranscriber(spk, build_stt(pack, http_session=http, endpointing_ms=300), pipeline.on_transcript)
               for spk in ("agent", "customer")}
        tasks = [asyncio.ensure_future(t.run()) for t in trs.values()]
        step = SR * chunk_ms // 1000
        t0 = time.monotonic()
        start_ms = now_ms()
        pipeline.metric(kind="replay_start", start_ms=start_ms, room=room, chunk_ms=chunk_ms, speed=speed,
                        source=str(audio_path or agent), controls=controls_on, llm=use_llm, stt=build_stt.__module__)
        for i in range(0, len(a), step):
            target = t0 + (i / SR) / speed
            await asyncio.sleep(max(0.0, target - time.monotonic()))
            arrival = now_ms()
            for spk, sig in (("agent", a), ("customer", c)):
                chunk = sig[i:i + step]
                if len(chunk) < step:
                    chunk = np.pad(chunk, (0, step - len(chunk)))
                trs[spk].push(rtc.AudioFrame(chunk.tobytes(), SR, 1, step), arrival)
        silence = np.zeros(step, dtype=np.int16).tobytes()
        for _ in range(int(1500 / chunk_ms)):  # flush trailing words
            for t in trs.values():
                t.push(rtc.AudioFrame(silence, SR, 1, step))
            await asyncio.sleep(chunk_ms / 1000)
        await asyncio.sleep(2.0)
        for t in trs.values():
            await t.aclose()
        for t in tasks:
            t.cancel()
    await asyncio.sleep(0.5)
    await pipeline.aclose()
    if hub_client:
        await hub_client.aclose()
    events_f.close()
    (out / "meta.json").write_text(json.dumps({"room": room, "pack": pack_id, "source": str(audio_path or agent),
                                               "start_ms": start_ms, "controls": controls_on, "llm": use_llm,
                                               "chunk_ms": chunk_ms, "labels": str(audio_path.parent / "labels.json") if audio_path else None},
                                              indent=2), encoding="utf-8")
    return out


async def replay_text(script_path: Path, *, use_llm: bool = False, controls_on: bool = True, virtual: bool = True,
                      out_dir: Path | None = None) -> dict:
    """Feeds script lines as final transcripts. Returns {"nudges": [...], "decisions": [...], "line_end_s": [...]}."""
    script = yaml.safe_load(script_path.read_text(encoding="utf-8"))
    pack = load_pack(script["pack"])
    events: list[dict] = []

    async def sink(e: dict) -> None:
        events.append(e)

    pipeline = CopilotPipeline(pack, sink, controls=Controls(enabled=controls_on), use_llm=use_llm,
                               metrics_path=(out_dir / "metrics.jsonl") if out_dir else None)
    base = time.time() * 1000
    if virtual:
        CLOCK.virtual = base
    t = 0.5
    line_end = []
    try:
        for i, (spk, text) in enumerate(script["lines"], start=1):
            t += len(text.split()) / WORDS_PER_S
            line_end.append(round(t, 2))
            if virtual:
                CLOCK.virtual = base + t * 1000
            else:
                await asyncio.sleep(len(text.split()) / WORDS_PER_S)
            u = Utterance(speaker=spk, text=text, final=True, utterance_id=f"{spk}-{i}", audio_received_at=base + t * 1000,
                          asr_at=base + t * 1000, confidence=0.95)
            await pipeline.on_transcript(u)
            await asyncio.sleep(0)
            t += 0.7
        if virtual:
            CLOCK.virtual = base + (t + 60) * 1000
        events += pipeline.engine.expire()
        await pipeline.aclose()
    finally:
        CLOCK.virtual = None
    nudges = [{**e["nudge"], "t_s": round((e["nudge"]["created_at"] - base) / 1000, 2)} for e in events if e["type"] == "nudge"]
    return {"script": script["id"], "nudges": nudges, "decisions": pipeline.engine.decisions, "line_end_s": line_end,
            "expected": script.get("expected", []), "base_ms": base}


def main() -> None:
    import rtc_warmup
    rtc_warmup.warm()
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", help="stereo audio file, or a script .yaml with --text")
    ap.add_argument("--agent")
    ap.add_argument("--customer")
    ap.add_argument("--pack", default="in_health")
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--controls", choices=["on", "off"], default="on")
    ap.add_argument("--chunk-ms", type=int, default=100)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--no-hub", action="store_true")
    ap.add_argument("--room")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    if a.text:
        res = asyncio.run(replay_text(Path(a.source), use_llm=not a.no_llm, controls_on=a.controls == "on"))
        for n in res["nudges"]:
            print(f"{n['t_s']:6.1f}s  P{n['priority']}  {n['key']:<28} {n['evidence']}")
        return
    out = asyncio.run(replay_audio(Path(a.source) if a.source else None, a.pack,
                                   agent=Path(a.agent) if a.agent else None, customer=Path(a.customer) if a.customer else None,
                                   chunk_ms=a.chunk_ms, speed=a.speed, use_llm=not a.no_llm,
                                   controls_on=a.controls == "on", hub=not a.no_hub, room=a.room))
    print(f"replay written to {out}")


if __name__ == "__main__":
    main()
