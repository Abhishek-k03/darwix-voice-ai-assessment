"""
Async streaming TTS worker — connects directly to a provider's WebSocket
streaming API (Fish Audio or Sarvam) rather than a batch/REST TTS call.

    stream_tts_worker(text_queue, audio_out_queue, interruption_event)

consumes LLM tokens from ``text_queue``, buffers them into clauses (flushed
on ',', '.', '?', '!', '\\n'), streams each clause into a persistent
provider WebSocket, and pushes raw PCM16 audio bytes onto
``audio_out_queue`` the instant they arrive — no batching, no waiting for
a full utterance.

Providers (env-driven, see TTSConfig):
    TTS_PROVIDER            fish | sarvam            (default: fish)
    TTS_API_KEY
    TTS_VOICE                                        (reference_id / speaker)
    TTS_LANGUAGE                                      (Sarvam only, default en-IN)
    TTS_SAMPLE_RATE                                    (default: 24000)
    TTS_FALLBACK_PROVIDER   fish | sarvam            (optional)
    TTS_FALLBACK_API_KEY                               (optional, defaults to TTS_API_KEY)

Protocol notes (verified against provider docs — not guessed):
  Fish Audio (wss://api.fish.audio/v1/tts/live): MessagePack-framed events
  {start, text, flush, stop} out / {audio, finish} in. Auth via
  ``Authorization: Bearer <key>`` header.
  https://docs.fish.audio/api-reference/endpoint/websocket/tts-live

  Sarvam (wss://api.sarvam.ai/text-to-speech/ws): JSON events
  {config, text, flush, ping} out / {audio (base64), event, error} in.
  Auth via ``api-subscription-key`` header.
  https://docs.sarvam.ai/api-reference-docs/text-to-speech-streaming/stream

Neither provider exposes a server-side "cancel this utterance but keep the
socket" primitive, so a barge-in reset (task 3) is implemented as: drain
both queues, then close and reopen the WebSocket. That still keeps the
connection persistent across normal turn boundaries (task 2) — a reconnect
only happens on interruption or an actual socket drop (task 4).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import ssl
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, replace
from typing import Any, Optional

import msgpack
import websockets

# Built once: a default context per connect costs ~250-500ms of blocked event loop on Windows.
_SSL = ssl.create_default_context()

logger = logging.getLogger("nexus.tts.stream")

# Pushed onto text_queue to mark "this LLM turn's tokens are complete" —
# flush the trailing partial clause, but keep the worker/connection alive.
TURN_END = object()

# Pushed onto text_queue to stop the worker entirely (session teardown).
SHUTDOWN = object()

CLAUSE_BOUNDARIES = {",", ".", "?", "!", "\n", "।"}  # "।" = Hindi full stop
SENTENCE_ENDS = {".", "?", "!", "\n", "।"}


# ── Clause buffering ───────────────────────────────────────────────────────


class ClauseBuffer:
    """Accumulates LLM tokens and yields complete clauses on punctuation.

    Iterates character-by-character since a single LLM token can contain
    zero, one, or several clause boundaries (tokens rarely align with
    punctuation), so this is the only way to catch every boundary.
    """

    def __init__(self) -> None:
        self._buf: list[str] = []
        self.flushed_in_turn = False  # first clause of a turn flushes early for low TTFB

    def push(self, token: str) -> list[str]:
        clauses: list[str] = []
        for ch in token:
            self._buf.append(ch)
            if ch in CLAUSE_BOUNDARIES:
                clause = "".join(self._buf).strip()
                self._buf.clear()
                if clause:
                    clauses.append(clause)
        return clauses

    def drain(self) -> Optional[str]:
        """Flush a trailing partial clause (e.g. end of turn). None if empty."""
        if not self._buf:
            return None
        clause = "".join(self._buf).strip()
        self._buf.clear()
        return clause or None

    def reset(self) -> None:
        self._buf.clear()
        self.flushed_in_turn = False


# ── Errors ──────────────────────────────────────────────────────────────────


class TTSConnectionError(Exception):
    """Raised when a provider WebSocket cannot be established after retries."""


class TTSProviderError(Exception):
    """Raised when the provider sends an explicit in-band error message."""


# ── Config ──────────────────────────────────────────────────────────────────


PROVIDER_KEY_ENV = {"fish": "FISH_API_KEY", "sarvam": "SARVAM_API_KEY", "deepgram": "DEEPGRAM_API_KEY",
                    "azure": "AZURE_SPEECH_KEY"}


def provider_key(provider: str) -> Optional[str]:
    if provider == "sarvam" and os.getenv("SARVAM_TTS", "off").lower() != "on":
        return None  # limited free credits: Sarvam is only used when explicitly switched on
    return os.getenv(PROVIDER_KEY_ENV.get(provider, ""), "") or (
        os.getenv("TTS_API_KEY") if os.getenv("TTS_PROVIDER", "").lower() == provider else None)


@dataclass(frozen=True)
class TTSConfig:
    provider: str
    api_key: Optional[str]
    voice: str
    language: str
    sample_rate: int
    fallback_provider: Optional[str]
    fallback_api_key: Optional[str]
    fallback_voice: Optional[str] = None
    fallback_language: Optional[str] = None
    model: str = ""
    fallback_model: str = ""

    @classmethod
    def from_env(cls) -> "TTSConfig":
        return cls(
            provider=os.getenv("TTS_PROVIDER", "fish").strip().lower(),
            api_key=os.getenv("TTS_API_KEY"),
            voice=os.getenv("TTS_VOICE", "default"),
            language=os.getenv("TTS_LANGUAGE", "en-IN"),
            sample_rate=int(os.getenv("TTS_SAMPLE_RATE", "24000")),
            fallback_provider=(os.getenv("TTS_FALLBACK_PROVIDER") or "").strip().lower() or None,
            fallback_api_key=os.getenv("TTS_FALLBACK_API_KEY"),
        )

    @classmethod
    def from_chain(cls, chain: list[dict], sample_rate: Optional[int] = None) -> "TTSConfig":
        """Pack preference list -> first provider with credentials as primary, next one as fallback.
        TTS_PROVIDER/TTS_VOICE env vars override the pack for experiments."""
        if os.getenv("TTS_PROVIDER"):
            forced = {"provider": os.getenv("TTS_PROVIDER").lower(), "voice": os.getenv("TTS_VOICE", "default"),
                      "language": os.getenv("TTS_LANGUAGE", "en-IN")}
            chain = [forced] + [c for c in chain if c["provider"] != forced["provider"]]
        usable = [c for c in chain if provider_key(c["provider"])] or chain[:1]
        primary = usable[0]
        fb = usable[1] if len(usable) > 1 else None
        return cls(
            provider=primary["provider"], api_key=provider_key(primary["provider"]), voice=primary.get("voice", "default"),
            language=primary.get("language", "en-IN"), sample_rate=sample_rate or int(os.getenv("TTS_SAMPLE_RATE", "24000")),
            fallback_provider=fb["provider"] if fb else None, fallback_api_key=provider_key(fb["provider"]) if fb else None,
            fallback_voice=fb.get("voice") if fb else None, fallback_language=fb.get("language") if fb else None,
            model=primary.get("model", ""), fallback_model=fb.get("model", "") if fb else "",
        )


# ── Provider client interface ────────────────────────────────────────────────


class TTSProviderClient(ABC):
    """Minimal interface every provider WebSocket client implements."""

    sample_rate: int
    num_channels: int = 1
    early_flushes_per_min: Optional[int] = None  # provider flush quota left for mid-turn flushes; None = unlimited

    def allow_early_flush(self) -> bool:
        """Turn-end flushes always go out; mid-turn ones only while the provider's per-minute quota allows."""
        if self.early_flushes_per_min is None:
            return True
        now = time.monotonic()
        recent = [t for t in getattr(self, "_early_flushes", []) if now - t < 60]
        if len(recent) >= self.early_flushes_per_min:
            self._early_flushes = recent
            return False
        self._early_flushes = recent + [now]
        return True

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def send_text(self, text: str) -> None:
        """Stream one clause of text into the provider's input buffer."""

    @abstractmethod
    async def flush(self) -> None:
        """Force the provider to synthesize whatever text is buffered so far."""

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def audio_chunks(self) -> AsyncIterator[bytes]:
        """Yield raw audio bytes as they arrive. Ends on close/drop/error."""


# ── Fish Audio client ────────────────────────────────────────────────────────

FISH_DEFAULT_URL = "wss://api.fish.audio/v1/tts/live"


class FishAudioClient(TTSProviderClient):
    def __init__(
        self,
        *,
        api_key: Optional[str],
        voice: str,
        sample_rate: int = 24000,
        model: str = "s1",
        url: str = FISH_DEFAULT_URL,
    ) -> None:
        self.sample_rate = sample_rate
        self.num_channels = 1
        self._api_key = api_key
        self._voice = voice
        self._model = model
        self._url = url
        self._ws: Optional[Any] = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(
            self._url,
            ssl=_SSL,
            additional_headers={
                "Authorization": f"Bearer {self._api_key}",
                "model": self._model,
            },
        )
        await self._send_event(
            {
                "event": "start",
                "request": {
                    "text": "",
                    "format": "pcm",
                    "chunk_length": 200,
                    "reference_id": self._voice,
                    "latency": "low",
                    "sample_rate": self.sample_rate,
                },
            }
        )

    async def _send_event(self, payload: dict) -> None:
        if self._ws is None:
            raise TTSConnectionError("Fish Audio client used before connect()")
        await self._ws.send(msgpack.packb(payload, use_bin_type=True))

    async def send_text(self, text: str) -> None:
        await self._send_event({"event": "text", "text": text})

    async def flush(self) -> None:
        await self._send_event({"event": "flush"})

    async def close(self) -> None:
        if self._ws is None:
            return
        with contextlib.suppress(Exception):
            await self._send_event({"event": "stop"})
        with contextlib.suppress(Exception):
            await self._ws.close()
        self._ws = None

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        if self._ws is None:
            raise TTSConnectionError("Fish Audio client used before connect()")
        async for raw in self._ws:
            msg = msgpack.unpackb(raw, raw=False)
            event = msg.get("event")
            if event == "audio":
                audio = msg.get("audio")
                if audio:
                    yield audio
            elif event == "finish":
                if msg.get("reason") == "error":
                    raise TTSProviderError("Fish Audio reported a synthesis error")
                return


# ── Sarvam client ─────────────────────────────────────────────────────────────

SARVAM_DEFAULT_URL = "wss://api.sarvam.ai/text-to-speech/ws"


class SarvamClient(TTSProviderClient):
    def __init__(
        self,
        *,
        api_key: Optional[str],
        voice: str,
        language: str = "en-IN",
        sample_rate: int = 24000,
        model: str = "bulbul:v2",
        url: str = SARVAM_DEFAULT_URL,
    ) -> None:
        self.sample_rate = sample_rate
        self.num_channels = 1
        self._api_key = api_key
        self._voice = voice
        self._language = language
        self._model = model
        self._url = url
        self._ws: Optional[Any] = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(
            self._url,
            ssl=_SSL,
            additional_headers={"api-subscription-key": self._api_key or ""},
        )
        await self._ws.send(
            json.dumps(
                {
                    "type": "config",
                    "data": {
                        "target_language_code": self._language,
                        "speaker": self._voice,
                        "model": self._model,
                        "speech_sample_rate": str(self.sample_rate) if self._model.endswith("v3") else self.sample_rate,
                        "output_audio_codec": "linear16",
                        "min_buffer_size": 50,
                        "max_chunk_length": 150 if self._model.endswith("v3") else 200,
                        "send_completion_event": True,
                    },
                }
            )
        )

    async def send_text(self, text: str) -> None:
        if self._ws is None:
            raise TTSConnectionError("Sarvam client used before connect()")
        await self._ws.send(json.dumps({"type": "text", "data": {"text": text}}))

    async def flush(self) -> None:
        if self._ws is None:
            raise TTSConnectionError("Sarvam client used before connect()")
        await self._ws.send(json.dumps({"type": "flush"}))

    async def close(self) -> None:
        if self._ws is None:
            return
        with contextlib.suppress(Exception):
            await self._ws.close()
        self._ws = None

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        if self._ws is None:
            raise TTSConnectionError("Sarvam client used before connect()")
        async for raw in self._ws:
            msg = json.loads(raw)
            msg_type = msg.get("type")
            if msg_type == "audio":
                b64_audio = msg.get("data", {}).get("audio")
                if b64_audio:
                    yield base64.b64decode(b64_audio)
            elif msg_type == "error":
                raise TTSProviderError(
                    msg.get("data", {}).get("message", "unknown Sarvam TTS error")
                )
            # "event"/"final" completion notices are informational only —
            # the connection stays open for the next turn.


# ── Deepgram Aura client ──────────────────────────────────────────────────────
# wss://api.deepgram.com/v1/speak — JSON {Speak, Flush, Close} out, binary PCM + JSON {Flushed, Metadata} in
# (protocol as implemented by livekit-plugins-deepgram's TTS stream).

DEEPGRAM_TTS_URL = "wss://api.deepgram.com/v1/speak"


class DeepgramClient(TTSProviderClient):
    early_flushes_per_min = 8  # Deepgram allows 20 Flush/60s per socket; the rest are reserved for turn ends

    def __init__(self, *, api_key: Optional[str], voice: str, sample_rate: int = 24000, url: str = DEEPGRAM_TTS_URL) -> None:
        self.sample_rate = sample_rate
        self.num_channels = 1
        self._api_key = api_key
        self._voice = voice if voice.startswith("aura") else "aura-2-thalia-en"
        self._url = url
        self._ws: Optional[Any] = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(
            f"{self._url}?model={self._voice}&encoding=linear16&sample_rate={self.sample_rate}",
            ssl=_SSL,
            additional_headers={"Authorization": f"Token {self._api_key}"},
        )

    async def _send(self, payload: dict) -> None:
        if self._ws is None:
            raise TTSConnectionError("Deepgram client used before connect()")
        await self._ws.send(json.dumps(payload))

    async def send_text(self, text: str) -> None:
        await self._send({"type": "Speak", "text": text + " "})

    async def flush(self) -> None:
        await self._send({"type": "Flush"})

    async def close(self) -> None:
        if self._ws is None:
            return
        with contextlib.suppress(Exception):
            await self._send({"type": "Close"})
        with contextlib.suppress(Exception):
            await self._ws.close()
        self._ws = None

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        if self._ws is None:
            raise TTSConnectionError("Deepgram client used before connect()")
        async for raw in self._ws:
            if isinstance(raw, (bytes, bytearray)):
                yield bytes(raw)
                continue
            msg = json.loads(raw)
            if msg.get("type") in ("Error", "Warning"):
                logger.warning("[tts] deepgram %s: %s", msg.get("type"), msg)
                if msg.get("type") == "Error":
                    raise TTSProviderError(str(msg))


# ── Azure Neural TTS client (Speech SDK) ──────────────────────────────────────
# Native fil-PH / id-ID / en-IN voices. The SDK keeps one pre-opened connection; each flushed clause is one
# SSML request; incremental audio arrives on the SDK's `synthesizing` event thread and is bridged into asyncio.

_AZURE_FORMATS = {8000: "Raw8Khz16BitMonoPcm", 16000: "Raw16Khz16BitMonoPcm", 24000: "Raw24Khz16BitMonoPcm",
                  48000: "Raw48Khz16BitMonoPcm"}
_CLOSED = object()


class AzureClient(TTSProviderClient):
    def __init__(self, *, api_key: Optional[str], voice: str, language: str, sample_rate: int = 24000,
                 region: Optional[str] = None) -> None:
        self.sample_rate = sample_rate
        self.num_channels = 1
        self._api_key = api_key
        self._region = region or os.getenv("AZURE_SPEECH_REGION", "southeastasia")
        self._voice = voice
        self._language = language
        self._buf: list[str] = []
        self._synth: Any = None
        self._conn: Any = None
        self._queue: "asyncio.Queue[Any]" = asyncio.Queue()

    async def connect(self) -> None:
        import azure.cognitiveservices.speech as speechsdk

        cfg = speechsdk.SpeechConfig(subscription=self._api_key, region=self._region)
        cfg.set_speech_synthesis_output_format(getattr(speechsdk.SpeechSynthesisOutputFormat, _AZURE_FORMATS[self.sample_rate]))
        self._synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
        loop = asyncio.get_running_loop()
        q = self._queue

        def _on_audio(evt) -> None:
            data = bytes(evt.result.audio_data)
            if data:
                loop.call_soon_threadsafe(q.put_nowait, data)

        def _on_cancel(evt) -> None:
            details = evt.result.cancellation_details
            if details.reason == speechsdk.CancellationReason.Error:
                loop.call_soon_threadsafe(q.put_nowait, TTSProviderError(details.error_details))

        self._synth.synthesizing.connect(_on_audio)
        self._synth.synthesis_canceled.connect(_on_cancel)
        self._conn = speechsdk.Connection.from_speech_synthesizer(self._synth)
        await asyncio.to_thread(self._conn.open, True)

    def _ssml(self, text: str) -> str:
        from xml.sax.saxutils import escape
        return (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{self._language}'>"
                f"<voice name='{self._voice}'>{escape(text)}</voice></speak>")

    async def send_text(self, text: str) -> None:
        self._buf.append(text)

    async def flush(self) -> None:
        text = " ".join(self._buf).strip()
        self._buf.clear()
        if text and self._synth is not None:
            self._synth.speak_ssml_async(self._ssml(text))

    async def close(self) -> None:
        if self._synth is not None:
            with contextlib.suppress(Exception):
                self._synth.stop_speaking_async()
            with contextlib.suppress(Exception):
                self._conn.close()
        self._synth = None
        self._queue.put_nowait(_CLOSED)

    async def audio_chunks(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._queue.get()
            if item is _CLOSED:
                return
            if isinstance(item, Exception):
                raise item
            yield item


def build_provider_client(
    provider: str, config: TTSConfig, *, api_key_override: Optional[str] = None
) -> TTSProviderClient:
    api_key = api_key_override or config.api_key
    if provider == "fish":
        return FishAudioClient(api_key=api_key, voice=config.voice, sample_rate=config.sample_rate)
    if provider == "sarvam":
        return SarvamClient(
            api_key=api_key,
            voice=config.voice,
            language=config.language,
            sample_rate=config.sample_rate,
            **({"model": config.model} if config.model else {}),
        )
    if provider == "deepgram":
        return DeepgramClient(api_key=api_key, voice=config.voice, sample_rate=config.sample_rate)
    if provider == "azure":
        return AzureClient(api_key=api_key, voice=config.voice, language=config.language, sample_rate=config.sample_rate)
    raise ValueError(f"unknown TTS provider: {provider!r}")


# ── Connection lifecycle (retry + fallback) ──────────────────────────────────


async def _connect_with_backoff(
    make_client: Callable[[], TTSProviderClient],
    *,
    max_retries: int = 4,
    base_delay: float = 0.25,
) -> TTSProviderClient:
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        client = make_client()
        try:
            await client.connect()
            return client
        except Exception as exc:  # noqa: BLE001 — any connect failure is retryable
            last_exc = exc
            delay = base_delay * (2**attempt)
            logger.warning(
                "[tts] connect attempt %d/%d failed: %s — retrying in %.2fs",
                attempt + 1,
                max_retries,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    raise TTSConnectionError(f"exhausted {max_retries} connect attempts") from last_exc


async def _connect_provider(config: TTSConfig) -> TTSProviderClient:
    try:
        return await _connect_with_backoff(lambda: build_provider_client(config.provider, config))
    except TTSConnectionError:
        if not config.fallback_provider or config.fallback_provider == config.provider:
            raise
        logger.error(
            "[tts] primary provider %r unreachable — falling back to %r",
            config.provider,
            config.fallback_provider,
        )
        fallback_key = config.fallback_api_key or config.api_key
        fb_config = replace(config, provider=config.fallback_provider,
                            voice=config.fallback_voice or config.voice,
                            language=config.fallback_language or config.language, model=config.fallback_model)
        return await _connect_with_backoff(
            lambda: build_provider_client(
                config.fallback_provider, fb_config, api_key_override=fallback_key
            )
        )


# ── Worker ────────────────────────────────────────────────────────────────────


def _drain_queue(queue: "asyncio.Queue[Any]") -> int:
    """Discard every currently-pending item without blocking."""
    count = 0
    while True:
        try:
            queue.get_nowait()
            count += 1
        except asyncio.QueueEmpty:
            return count


async def _pump_audio(client: TTSProviderClient, audio_out_queue: "asyncio.Queue[bytes]") -> None:
    async for chunk in client.audio_chunks():
        await audio_out_queue.put(chunk)


async def _run_session(
    client: TTSProviderClient,
    text_queue: "asyncio.Queue[Any]",
    audio_out_queue: "asyncio.Queue[bytes]",
    interruption_event: asyncio.Event,
    clause_buf: ClauseBuffer,
) -> str:
    """Run one WebSocket session: pump text in, pump audio out, watch for
    barge-in. Returns "shutdown", "interrupted", or "dropped" so the caller
    knows whether to stop, purge+reconnect, or just reconnect."""
    audio_task = asyncio.ensure_future(_pump_audio(client, audio_out_queue))
    interrupt_task = asyncio.ensure_future(interruption_event.wait())
    try:
        while True:
            get_task = asyncio.ensure_future(text_queue.get())
            done, _pending = await asyncio.wait(
                {get_task, audio_task, interrupt_task}, return_when=asyncio.FIRST_COMPLETED
            )

            if interrupt_task in done:
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await get_task
                return "interrupted"

            if audio_task in done:
                get_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await get_task
                exc = audio_task.exception()
                if exc:
                    logger.warning("[tts] audio stream dropped: %s", exc)
                else:
                    logger.warning("[tts] audio stream ended unexpectedly")
                return "dropped"

            item = get_task.result()
            if item is SHUTDOWN:
                return "shutdown"
            if item is TURN_END:
                trailing = clause_buf.drain()
                if trailing:
                    await client.send_text(trailing)
                await client.flush()
                clause_buf.flushed_in_turn = False
                continue

            # flush the first clause at once (TTFB), then only at sentence ends: per-comma flushes left
            # audible gaps mid-sentence
            for clause in clause_buf.push(item):
                if not any(c.isalnum() for c in clause):
                    continue  # "....." runs: nothing to say, and each would cost a flush
                await client.send_text(clause)
                if (not clause_buf.flushed_in_turn or clause[-1] in SENTENCE_ENDS) and client.allow_early_flush():
                    await client.flush()
                    clause_buf.flushed_in_turn = True
    finally:
        for task in (audio_task, interrupt_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(audio_task, interrupt_task, return_exceptions=True)


async def stream_tts_worker(
    text_queue: "asyncio.Queue[Any]",
    audio_out_queue: "asyncio.Queue[Any]",
    interruption_event: asyncio.Event,
    *,
    config: Optional[TTSConfig] = None,
    connect: Optional[Callable[[], Coroutine[Any, Any, TTSProviderClient]]] = None,
) -> None:
    """Consume LLM tokens from ``text_queue``, stream them to the configured
    TTS provider over a persistent WebSocket, and push raw audio bytes onto
    ``audio_out_queue`` as they arrive.

    Push ``TURN_END`` onto text_queue when one LLM turn's tokens are done
    (flushes the trailing clause, connection stays open). Push ``SHUTDOWN``
    to stop the worker for good (closes the connection and returns).

    ``connect`` is an injectable ``() -> TTSProviderClient`` factory, mainly
    for tests; defaults to the real env-configured provider with retry +
    fallback.
    """
    config = config or TTSConfig.from_env()
    connect = connect or (lambda: _connect_provider(config))

    clause_buf = ClauseBuffer()
    client = await connect()
    logger.info("[tts] connected via %s", type(client).__name__)

    try:
        while True:
            outcome = await _run_session(
                client, text_queue, audio_out_queue, interruption_event, clause_buf
            )

            if outcome == "shutdown":
                break

            if outcome == "interrupted":
                logger.info("[tts] barge-in — purging audio buffer and resetting stream")
                _drain_queue(audio_out_queue)
                _drain_queue(text_queue)
                clause_buf.reset()
                interruption_event.clear()

            # Both "interrupted" and "dropped" leave the socket in a state we
            # don't trust — close it and open a fresh one before resuming.
            await client.close()
            client = await connect()
            logger.info("[tts] reconnected via %s (reason=%s)", type(client).__name__, outcome)
    finally:
        await client.close()
