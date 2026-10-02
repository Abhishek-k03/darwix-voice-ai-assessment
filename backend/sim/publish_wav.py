"""Publish a two-party recording into a LiveKit room at real-time speed (agent and customer as separate
participants), with the live copilot dispatched into the same room — the full live Q4 path without telephony.
Port of ai-ear's sim_call.py (10 ms frames).

  uv run python -m sim.publish_wav ../evidence/q4/scripted/missed_cross_sell/stereo.wav --pack in_health
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
from dotenv import find_dotenv, load_dotenv
from livekit import api, rtc

load_dotenv(find_dotenv())
SR, FRAME_MS = 16000, 10


def _token(room: str, identity: str, role: str) -> str:
    return (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(identity).with_attributes({"role": role})
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=False)).to_jwt())


async def publish(room_name: str, identity: str, role: str, pcm: np.ndarray, start: asyncio.Event) -> None:
    room = rtc.Room()
    await room.connect(os.environ["LIVEKIT_URL"], _token(room_name, identity, role))
    source = rtc.AudioSource(SR, 1)
    track = rtc.LocalAudioTrack.create_audio_track(f"{identity}-audio", source)
    await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    await start.wait()
    step = SR * FRAME_MS // 1000
    for i in range(0, len(pcm), step):
        chunk = pcm[i:i + step]
        if len(chunk) < step:
            chunk = np.pad(chunk, (0, step - len(chunk)))
        await source.capture_frame(rtc.AudioFrame(chunk.tobytes(), SR, 1, step))
    await asyncio.sleep(2.0)
    await room.disconnect()


def _play_locally(path: Path) -> None:
    """Play the recording on this machine's speakers so a screen recording captures the call audio."""
    try:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
    except ImportError:
        print("--play needs Windows (winsound); continuing without local playback")


async def main_async(path: Path, pack: str, room: str | None, wait_s: float, play: bool = False) -> None:
    data, sr = sf.read(path, dtype="int16", always_2d=True)
    assert sr == SR, "expects 16 kHz (output of sim.make_scripted_call)"
    room = room or f"live-{path.parent.name}-{uuid.uuid4().hex[:4]}"
    lk = api.LiveKitAPI(os.environ["LIVEKIT_URL"], os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
    await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
        agent_name=os.getenv("COPILOT_AGENT_NAME", "call-copilot"), room=room,
        metadata=json.dumps({"pack": pack, "mode": "replay_live", "role": "copilot"})))
    await lk.aclose()
    print(f"room {room} — dashboard: {os.getenv('FRONTEND_URL', 'http://localhost:3000')}/copilot/{room}")
    start = asyncio.Event()
    tasks = [asyncio.ensure_future(publish(room, "agent-human", "advisor", data[:, 0], start)),
             asyncio.ensure_future(publish(room, "customer-sim", "customer", data[:, 1], start))]
    await asyncio.sleep(wait_s)  # let the copilot join and subscribe before audio starts
    if play:
        _play_locally(path)
    start.set()
    await asyncio.gather(*tasks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stereo")
    ap.add_argument("--pack", default="in_health")
    ap.add_argument("--room")
    ap.add_argument("--wait", type=float, default=6.0)
    ap.add_argument("--play", action="store_true", help="also play the recording on local speakers (for screen recordings)")
    a = ap.parse_args()
    asyncio.run(main_async(Path(a.stereo).resolve(), a.pack, a.room, a.wait, a.play))


if __name__ == "__main__":
    main()
