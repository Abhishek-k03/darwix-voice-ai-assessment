"""
Publishes raw PCM16 audio bytes from an asyncio.Queue onto a LiveKit
WebRTC audio track.

This is the consumer side of tts_streamer.py's audio_out_queue: it
re-chunks the provider's irregular, bursty byte deliveries into uniform
frames and feeds them to ``livekit.rtc.AudioSource``, which owns its own
internal playout buffer (``queue_size_ms``) and paces frames onto the
wire in real time — that's what actually prevents audible stuttering
from network/provider jitter, not anything on the Python side. On
barge-in it calls ``AudioSource.clear_queue()`` to drop already-captured,
not-yet-played audio immediately, matching tts_streamer.py's own purge of
audio_out_queue for anything not yet captured.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Optional

from livekit import rtc

from tts_streamer import SHUTDOWN

logger = logging.getLogger("nexus.tts.track")

FRAME_MS = 20
BYTES_PER_SAMPLE = 2  # PCM16
DEFAULT_QUEUE_SIZE_MS = 400  # AudioSource internal playout buffer


class _FrameChunker:
    """Buffers arbitrary-length PCM16 byte runs into fixed-duration frames."""

    def __init__(self, sample_rate: int, num_channels: int, frame_ms: int = FRAME_MS) -> None:
        self._frame_bytes = (
            int(sample_rate * frame_ms / 1000) * BYTES_PER_SAMPLE * num_channels
        )
        self._buf = bytearray()

    def push(self, chunk: bytes) -> list[bytes]:
        self._buf.extend(chunk)
        frames = []
        while len(self._buf) >= self._frame_bytes:
            frames.append(bytes(self._buf[: self._frame_bytes]))
            del self._buf[: self._frame_bytes]
        return frames

    def reset(self) -> None:
        self._buf.clear()


def _make_frame(data: bytes, sample_rate: int, num_channels: int) -> rtc.AudioFrame:
    return rtc.AudioFrame(
        data=data,
        sample_rate=sample_rate,
        num_channels=num_channels,
        samples_per_channel=len(data) // (BYTES_PER_SAMPLE * num_channels),
    )


class PlaybackTracker:
    """Knows whether the bot is audibly speaking (AgentSession can't: its own audio output is disabled)."""

    def __init__(self) -> None:
        self.last_frame_at = 0.0

    def mark(self) -> None:
        self.last_frame_at = time.monotonic()

    def speaking(self, hangover_s: float = 0.3) -> bool:
        return time.monotonic() - self.last_frame_at < hangover_s

    async def wait_idle(self, audio_queue: "asyncio.Queue", silence_s: float = 0.8, timeout_s: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if audio_queue.empty() and time.monotonic() - self.last_frame_at > silence_s:
                return
            await asyncio.sleep(0.1)


async def publish_audio_track(
    room: rtc.Room,
    audio_out_queue: "asyncio.Queue[bytes]",
    interruption_event: asyncio.Event,
    *,
    sample_rate: int,
    num_channels: int = 1,
    track_name: str = "nexus-tts",
    queue_size_ms: int = DEFAULT_QUEUE_SIZE_MS,
    on_frame: Optional[Callable[[bytes], None]] = None,
    tracker: Optional[PlaybackTracker] = None,
) -> asyncio.Task:
    """Publish a LocalAudioTrack fed entirely from audio_out_queue.

    Watches the same interruption_event as stream_tts_worker so a barge-in
    clears already-buffered WebRTC audio immediately, not just the queue.
    Returns the background task driving the publish loop — cancel it to
    stop publishing (e.g. on session teardown).
    """
    source = rtc.AudioSource(sample_rate, num_channels, queue_size_ms=queue_size_ms)
    track = rtc.LocalAudioTrack.create_audio_track(track_name, source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await room.local_participant.publish_track(track, options)
    logger.info(
        "[tts-track] published %r @ %dHz (queue_size_ms=%d)",
        track_name,
        sample_rate,
        queue_size_ms,
    )

    task = asyncio.ensure_future(
        _pump(source, audio_out_queue, interruption_event, sample_rate, num_channels, on_frame, tracker)
    )
    return task


async def _pump(
    source: rtc.AudioSource,
    audio_out_queue: "asyncio.Queue[bytes]",
    interruption_event: asyncio.Event,
    sample_rate: int,
    num_channels: int,
    on_frame: Optional[Callable[[bytes], None]] = None,
    tracker: Optional[PlaybackTracker] = None,
) -> None:
    chunker = _FrameChunker(sample_rate, num_channels)
    interrupt_task: Optional[asyncio.Task] = asyncio.ensure_future(interruption_event.wait())
    try:
        while True:
            get_task = asyncio.ensure_future(audio_out_queue.get())
            done, _pending = await asyncio.wait(
                {get_task, interrupt_task}, return_when=asyncio.FIRST_COMPLETED
            )

            if interrupt_task in done:
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await get_task
                source.clear_queue()
                chunker.reset()
                logger.info("[tts-track] barge-in — cleared LiveKit audio source queue")
                # interruption_event.clear() is owned by stream_tts_worker;
                # wait for it before re-arming so we don't spin.
                while interruption_event.is_set():
                    await asyncio.sleep(0.01)
                interrupt_task = asyncio.ensure_future(interruption_event.wait())
                continue

            item = get_task.result()
            if item is SHUTDOWN:
                break
            for frame_bytes in chunker.push(item):
                await source.capture_frame(_make_frame(frame_bytes, sample_rate, num_channels))
                if tracker:
                    tracker.mark()
                if on_frame:
                    on_frame(frame_bytes)
    finally:
        if interrupt_task and not interrupt_task.done():
            interrupt_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await interrupt_task
