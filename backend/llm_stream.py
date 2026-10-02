"""
Provider-agnostic async LLM token streaming.

Wraps an OpenAI-compatible ``AsyncOpenAI`` client so the inference
provider is a runtime config, not a hardcoded plugin — point it at Groq,
Cerebras, or any other OpenAI-compatible endpoint via env vars:

    LLM_BASE_URL   default: https://api.groq.com/openai/v1
    LLM_API_KEY
    LLM_MODEL      e.g. llama-3.3-70b-versatile, llama3.3-70b, qwen-3-instruct

Tokens are pushed onto an ``asyncio.Queue`` the instant each delta arrives
on the wire — never accumulated into sentences or the full completion —
so downstream consumers (TTS, SSE, benchmarks) can start acting on the
first token immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Optional

from openai import APIConnectionError, AsyncOpenAI, InternalServerError, RateLimitError

from latency import StreamLatency

logger = logging.getLogger("nexus.llm.stream")

# Sentinel placed on the queue to signal end-of-stream to consumers.
# An object() identity check is unambiguous even if a real token is falsy.
STREAM_DONE = object()

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"
FAST_DEFAULT_MODEL = "openai/gpt-oss-20b"


def reasoning_kwargs(model: str) -> dict:
    """gpt-oss models reason before answering; low effort keeps voice TTFT ~200-450 ms on Groq."""
    return {"reasoning_effort": os.getenv("LLM_REASONING_EFFORT", "low")} if "gpt-oss" in model else {}


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: Optional[str]
    model: str
    fallback_models: tuple[str, ...] = ()  # same provider, own quota: used on 429 / outage

    @classmethod
    def from_env(cls, prefix: str = "") -> "LLMConfig":
        """prefix="FAST_" / "SIM_" reads FAST_LLM_* etc., falling back to LLM_* for anything unset."""
        def _get(name: str, default: Optional[str] = None) -> Optional[str]:
            return (os.getenv(f"{prefix}{name}") if prefix else None) or os.getenv(name, default)

        default_model = FAST_DEFAULT_MODEL if prefix in ("FAST_", "SIM_") else DEFAULT_MODEL
        return cls(
            base_url=_get("LLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=_get("LLM_API_KEY"),
            model=(os.getenv(f"{prefix}LLM_MODEL") if prefix else None) or (default_model if prefix else os.getenv("LLM_MODEL", DEFAULT_MODEL)),
            fallback_models=tuple(m.strip() for m in (_get("LLM_FALLBACK_MODELS") or "").split(",") if m.strip()),
        )


MODEL_COOLDOWN_S = 60.0
_cooling: dict[str, float] = {}
_key_clients: dict[tuple[int, str], AsyncOpenAI] = {}


def targets(config: LLMConfig) -> list[tuple[str, Optional[str], str]]:
    """(model, api_key, label) for the model then each fallback. 'model@ENV_VAR' runs that model on the key held in
    ENV_VAR (a second account's quota); entries whose key is unset are skipped. Labels never contain the key."""
    out = []
    for entry in dict.fromkeys((config.model, *config.fallback_models)):
        model, _, var = entry.partition("@")
        key = os.getenv(var) if var else config.api_key
        if key:
            out.append((model, key, entry))
    return out


def _client_for(config: LLMConfig, api_key: str) -> AsyncOpenAI:
    k = (id(asyncio.get_running_loop()), api_key)  # one client per event loop (LiveKit job threads)
    if k not in _key_clients:
        _key_clients[k] = AsyncOpenAI(base_url=config.base_url, api_key=api_key)
    return _key_clients[k]


async def create_completion(client: AsyncOpenAI, config: LLMConfig, **kwargs):
    """chat.completions.create over targets(config). A 429 / 5xx / connection error cools that target for a minute
    and moves on: free tiers cap tokens per model per day."""
    chain = targets(config)
    now = time.monotonic()
    last: Optional[Exception] = None
    for model, key, label in [t for t in chain if _cooling.get(t[2], 0) <= now] or chain[:1]:
        try:
            c = client if key == config.api_key else _client_for(config, key)
            return await c.chat.completions.create(model=model, **kwargs, **reasoning_kwargs(model))
        except (RateLimitError, InternalServerError, APIConnectionError) as exc:
            _cooling[label] = time.monotonic() + MODEL_COOLDOWN_S
            logger.warning("[llm] %s unavailable (%s), trying the next model", label, type(exc).__name__)
            last = exc
    raise last


def build_client(config: Optional[LLMConfig] = None) -> AsyncOpenAI:
    """Construct the shared AsyncOpenAI client for the configured provider."""
    config = config or LLMConfig.from_env()
    return AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)


async def stream_to_queue(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    queue: "asyncio.Queue[Any]",
    *,
    request_id: Optional[str] = None,
    **create_kwargs: Any,
) -> dict:
    """Stream a chat completion token-by-token onto ``queue``.

    Puts ``STREAM_DONE`` on the queue when the stream ends, whether it
    finished normally or raised, so consumers never have to poll for
    completion. Returns the latency benchmark summary (ttft_ms, tps, ...).
    """
    request_id = request_id or uuid.uuid4().hex[:8]
    bench = StreamLatency(request_id=request_id, model=model)

    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            **create_kwargs,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            token = chunk.choices[0].delta.content
            if not token:
                continue
            bench.record_token()
            await queue.put(token)
        return bench.finish()
    finally:
        await queue.put(STREAM_DONE)


async def stream_completion(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    *,
    request_id: Optional[str] = None,
    **create_kwargs: Any,
) -> AsyncIterator[str]:
    """Async-generator convenience wrapper around ``stream_to_queue``.

    For callers that want ``async for token in stream_completion(...)``
    (e.g. an SSE endpoint) instead of owning the queue directly.
    """
    queue: asyncio.Queue = asyncio.Queue()
    producer = asyncio.create_task(
        stream_to_queue(
            client, model, messages, queue, request_id=request_id, **create_kwargs
        )
    )
    try:
        while True:
            item = await queue.get()
            if item is STREAM_DONE:
                break
            yield item
    finally:
        if not producer.done():
            producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer
