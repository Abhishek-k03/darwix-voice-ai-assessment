"""One streaming STT per speaker (agent / customer tracks are separate -> exact speaker separation).

Transcription latency is measured per result against a frame-arrival mark table (ported from ai-ear
transcribe_stream): result.end_time (seconds into this stream) -> wall time the frame holding that audio arrived.
"""

from __future__ import annotations

import bisect
import logging
from collections.abc import Awaitable, Callable

from livekit import rtc
from livekit.agents import stt as lk_stt

from .events import Utterance, now_ms

logger = logging.getLogger("copilot.stt")


class SpeakerTranscriber:
    def __init__(self, speaker: str, engine: lk_stt.STT, on_utterance: Callable[[Utterance], Awaitable[None]]) -> None:
        self.speaker = speaker
        self.stream = engine.stream()
        self.on_utterance = on_utterance
        self.audio_s = 0.0
        self._marks: list[tuple[float, float]] = []
        self._seq = 0
        self.results = 0

    def push(self, frame: rtc.AudioFrame, arrival_ms: float | None = None) -> None:
        self.audio_s += frame.samples_per_channel / frame.sample_rate
        self._marks.append((self.audio_s, arrival_ms or now_ms()))
        if len(self._marks) > 12000:
            del self._marks[:4000]
        self.stream.push_frame(frame)

    def _arrival(self, end_s: float) -> float:
        if not self._marks:
            return now_ms()
        if end_s <= 0:
            return self._marks[-1][1]
        i = bisect.bisect_left(self._marks, (end_s,))
        return self._marks[min(i, len(self._marks) - 1)][1]

    async def run(self) -> None:
        async for ev in self.stream:
            if ev.type not in (lk_stt.SpeechEventType.INTERIM_TRANSCRIPT, lk_stt.SpeechEventType.FINAL_TRANSCRIPT):
                continue
            if not ev.alternatives or not ev.alternatives[0].text.strip():
                continue
            alt = ev.alternatives[0]
            final = ev.type == lk_stt.SpeechEventType.FINAL_TRANSCRIPT
            u = Utterance(speaker=self.speaker, text=alt.text.strip(), final=final, utterance_id=f"{self.speaker}-{self._seq}",
                          audio_received_at=self._arrival(alt.end_time), asr_at=now_ms(),
                          confidence=alt.confidence or 1.0, start_s=alt.start_time, end_s=alt.end_time)
            self.results += 1
            if final:
                self._seq += 1
            try:
                await self.on_utterance(u)
            except Exception:  # noqa: BLE001 — a bad event must not stop transcription
                logger.exception("[copilot] utterance handler failed")

    async def aclose(self) -> None:
        self.stream.end_input()
        await self.stream.aclose()
