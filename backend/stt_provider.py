"""Per-pack STT factory (mirrors llm_provider.py): the market's ASR choice is configuration, not code.

pack.stt may be one dict or a preference list; the first provider with credentials wins.
"""

from __future__ import annotations

import logging
import os

from livekit.agents import stt as lk_stt
from livekit.plugins import azure, deepgram  # plugins must register on the main thread (import-time)

from packs import Pack

try:
    from livekit.plugins import gladia
except ImportError:  # optional bake-off provider
    gladia = None

logger = logging.getLogger("nexus.stt")

KEY_ENV = {"deepgram": "DEEPGRAM_API_KEY", "azure": "AZURE_SPEECH_KEY", "gladia": "GLADIA_API_KEY"}


def _chain(pack: Pack) -> list[dict]:
    cfg = pack.stt
    return cfg if isinstance(cfg, list) else [cfg]


def resolve(pack: Pack, override: str | None = None) -> dict:
    chain = _chain(pack)
    if override:
        chain = [c for c in chain if c["provider"] == override] or [{**chain[0], "provider": override}]
    for c in chain:
        if os.getenv(KEY_ENV.get(c["provider"], ""), ""):
            return c
    logger.warning("no STT credentials for pack %s; using %s anyway", pack.id, chain[0]["provider"])
    return chain[0]


def build_stt(pack: Pack, override: str | None = None, http_session=None, endpointing_ms: int | None = None) -> lk_stt.STT:
    """http_session is only needed outside a LiveKit job (offline replay / ASR bench)."""
    c = resolve(pack, override or os.getenv("STT_PROVIDER_OVERRIDE") or None)
    p = c["provider"]
    session = {"http_session": http_session} if http_session is not None else {}
    if p == "deepgram":
        extra = {"keyterm": c["keyterms"]} if c.get("keyterms") and str(c.get("model", "")).startswith("nova-3") else {}
        return deepgram.STT(model=c.get("model", "nova-3"), language=c.get("language", "en-US"), smart_format=True,
                            punctuate=True, interim_results=True,
                            endpointing_ms=endpointing_ms or c.get("endpointing_ms", 25), **extra, **session)
    if p == "azure":
        langs = c.get("languages") or c.get("language")
        return azure.STT(speech_key=os.getenv("AZURE_SPEECH_KEY"), speech_region=os.getenv("AZURE_SPEECH_REGION"),
                         language=langs, phrase_list=c.get("keyterms") or None)
    if p == "gladia":
        if gladia is None:
            raise ValueError("gladia plugin not installed (uv add livekit-plugins-gladia)")
        return gladia.STT(languages=c.get("languages") or [c.get("language", "en")], code_switching=True, **session)
    raise ValueError(f"unknown STT provider {p!r}")


def describe(pack: Pack) -> dict:
    c = resolve(pack)
    return {"provider": c["provider"], "model": c.get("model"), "language": c.get("languages") or c.get("language")}
