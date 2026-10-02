"""Live copilot worker: joins the SAME LiveKit room as the call (explicit dispatch), never publishes audio,
transcribes each participant's track separately and streams signals/nudges to the hub in real time.

Run: uv run python -m livekit.agents start copilot/worker.py --dev
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import find_dotenv, load_dotenv  # noqa: E402
from livekit import rtc  # noqa: E402
from livekit.agents import AgentServer, AutoSubscribe, JobContext  # noqa: E402

from copilot import audio_apm  # noqa: E402
from copilot.events import now_ms, typed_utterance  # noqa: E402
from copilot.hub_client import HubClient  # noqa: E402
from copilot.pipeline import CopilotPipeline  # noqa: E402
from copilot.stt_stream import SpeakerTranscriber  # noqa: E402
from packs import load_pack  # noqa: E402
import rtc_warmup  # noqa: E402
from roles import role_of  # noqa: E402
from stt_provider import build_stt  # noqa: E402

load_dotenv(find_dotenv())
os.environ.setdefault("LIVEKIT_AGENT_NAME", "call-copilot")
logger = logging.getLogger("copilot.worker")
METRICS_DIR = Path(__file__).resolve().parents[2] / "evidence" / "q4" / "metrics"
SPEAKER = {"voice_agent": "agent", "advisor": "agent", "customer": "customer"}

rtc_warmup.warm()
server = AgentServer(**rtc_warmup.server_kwargs())


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    pack = load_pack(meta.get("pack"))
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.room.local_participant.set_attributes({"role": "copilot"})
    hub = HubClient(ctx.room.name)
    hub.start()
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline = CopilotPipeline(pack, hub.send, metrics_path=METRICS_DIR / f"{ctx.room.name}.jsonl")
    await pipeline.start()
    transcribers: dict[str, SpeakerTranscriber] = {}
    tasks: list[asyncio.Task] = []

    async def pump(track: rtc.Track, tr: SpeakerTranscriber) -> None:
        apm = audio_apm.build_apm()
        stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1,
                                 frame_size_ms=audio_apm.FRAME_MS if apm else None)
        async for ev in stream:
            tr.push(audio_apm.process(apm, ev.frame), now_ms())

    def attach(track: rtc.Track, participant: rtc.RemoteParticipant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO or track.sid in transcribers:
            return
        speaker = SPEAKER.get(role_of(participant))
        if not speaker:
            return
        tr = SpeakerTranscriber(speaker, build_stt(pack, endpointing_ms=500), pipeline.on_transcript)
        transcribers[track.sid] = tr
        tasks.extend([asyncio.ensure_future(tr.run()), asyncio.ensure_future(pump(track, tr))])
        logger.info("[copilot] transcribing %s (%s)", participant.identity, speaker)

    @ctx.room.on("track_subscribed")
    def _on_track(track, _pub, participant):
        attach(track, participant)

    typed_seq = 0

    @ctx.room.on("data_received")
    def _on_data(pkt) -> None:
        nonlocal typed_seq
        if pkt.topic != "transcript":
            return
        try:
            u = typed_utterance(json.loads(pkt.data.decode()), typed_seq)
        except ValueError:
            return
        if u:
            typed_seq += 1
            tasks.append(asyncio.ensure_future(pipeline.on_transcript(u)))

    @ctx.room.on("participant_attributes_changed")
    def _on_attrs(_changed, participant):
        for pub in participant.track_publications.values():
            if pub.track:
                attach(pub.track, participant)

    for p in ctx.room.remote_participants.values():
        for pub in p.track_publications.values():
            if pub.track:
                attach(pub.track, p)

    async def _cleanup(*_a) -> None:
        for tr in transcribers.values():
            await tr.aclose()
        for t in tasks:
            t.cancel()
        await pipeline.aclose()
        await hub.aclose()

    ctx.add_shutdown_callback(_cleanup)


if __name__ == "__main__":
    from livekit.agents import cli
    cli.run_app(server)
