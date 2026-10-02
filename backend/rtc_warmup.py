"""Windows workaround for a native race in livekit_ffi's bundled soxr resampler.

soxr lazily builds a global FFT cache without locking (soxr-sys fft4g_cache.h: assert LSX_FFT_BR == NULL). When two
audio streams start resampling at the same time (RoomIO input, VAD, STT, recorder, copilot), the second init trips the
assert and the MSVC runtime blocks the process behind a modal "Assertion failed" dialog. We (1) build the cache once,
single-threaded, at worker start for every rate/quality combination we use, and (2) send CRT assert output to stderr
so any remaining failure crashes visibly instead of hanging on a dialog.
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger("rtc.warmup")
RATES = (8000, 16000, 24000, 44100, 48000)
_done = False


def server_kwargs() -> dict:
    """JOB_EXECUTOR=process runs each call in its own process (more isolation, slower start)."""
    import os
    if os.getenv("JOB_EXECUTOR", "").lower() == "process":
        from livekit.agents import JobExecutorType
        return {"job_executor_type": JobExecutorType.PROCESS}
    return {}


def _crt_asserts_to_stderr() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.cdll.ucrtbase._set_error_mode(1)  # _OUT_TO_STDERR: no modal assert dialog
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not redirect CRT asserts: %s", exc)


def _utf8_console() -> None:
    """Windows consoles default to cp1252: any non-ASCII log line (Bahasa, Tagalog, arrows) raised a logging error."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def warm() -> None:
    global _done
    if _done:
        return
    _done = True
    _utf8_console()
    _crt_asserts_to_stderr()
    from livekit import rtc

    n = 0
    for quality in rtc.AudioResamplerQuality:
        for channels in (1, 2):
            for src in RATES:
                for dst in RATES:
                    if src == dst:
                        continue
                    r = rtc.AudioResampler(src, dst, num_channels=channels, quality=quality)
                    samples = src // 10  # 100 ms
                    r.push(rtc.AudioFrame(bytes(samples * channels * 2), src, channels, samples))
                    r.flush()
                    n += 1
    logger.info("[warmup] soxr FFT cache initialised (%d resamplers)", n)
