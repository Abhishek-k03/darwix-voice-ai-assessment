"""Optional WebRTC pre-processing before STT (ported from ai-ear audio_apm). COPILOT_APM="ns,hpf,agc"; empty = off.
APM needs 10 ms frames. Echo cancellation is omitted: the copilot is passive (no far-end reference)."""

from __future__ import annotations

import os

from livekit import rtc

FRAME_MS = 10


def build_apm(spec: str | None = None):
    flags = {s.strip() for s in (spec if spec is not None else os.getenv("COPILOT_APM", "")).split(",") if s.strip()}
    if not flags:
        return None
    unknown = flags - {"ns", "hpf", "agc"}
    if unknown:
        raise ValueError(f"unknown COPILOT_APM flags: {sorted(unknown)}")
    return rtc.AudioProcessingModule(noise_suppression="ns" in flags, high_pass_filter="hpf" in flags,
                                     auto_gain_control="agc" in flags, echo_cancellation=False)


def process(apm, frame: rtc.AudioFrame) -> rtc.AudioFrame:
    if apm is None or frame.samples_per_channel * 1000 // frame.sample_rate != FRAME_MS:
        return frame
    apm.process_stream(frame)
    return frame
