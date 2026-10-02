"""Simulated customer (LLM persona) that joins the same LiveKit room as the voice agent and talks to it through
real STT/TTS — so recorded test calls exercise the full production audio path, reproducibly.

Dispatched by POST /sim/start {pack, scenario}. Personas: sim/personas/<pack>/<scenario>.yaml.
Run: uv run python -m livekit.agents start sim/caller_bot.py --dev
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402
from dotenv import find_dotenv, load_dotenv  # noqa: E402
from livekit.agents import Agent, AgentServer, AgentSession, AutoSubscribe, JobContext  # noqa: E402
from livekit.agents.llm import ChatChunk, ChoiceDelta  # noqa: E402
from livekit.agents.voice import room_io  # noqa: E402
from livekit.plugins import azure, deepgram  # noqa: E402  (register on main thread)
from livekit.plugins import silero  # noqa: E402

from llm_provider import build_llm  # noqa: E402  (registers the openai plugin on the main thread)
from llm_stream import LLMConfig  # noqa: E402
from packs import load_pack  # noqa: E402
import rtc_warmup  # noqa: E402
from roles import KIND_AGENT, wait_for_role  # noqa: E402
from stt_provider import build_stt  # noqa: E402

load_dotenv(find_dotenv())
os.environ.setdefault("LIVEKIT_AGENT_NAME", "sim-caller")
logger = logging.getLogger("sim.caller")
PERSONAS = Path(__file__).parent / "personas"

CALLER_RULES = """
You are role-playing ONE person: the CUSTOMER who received a phone call. The messages you receive are what the
company's assistant just said. Your replies are only what the customer says back.
- You are NOT the assistant. Never ask the assistant about age, city, budget or family, never offer or schedule a
  callback, never say "I'll schedule", "our advisers", "how can I help" or anything the assistant would say.
- Reply to the assistant's latest message only, in one or two short spoken sentences, like a real person. Then stop
  and wait. Never continue the conversation by yourself or answer questions that have not been asked yet.
- Reveal a fact from your notes only when the assistant asks for it. Use a reaction from your notes only when its
  trigger happens.
- Plain spoken text only. Never describe yourself as an AI. You hang up automatically when the assistant closes.
"""
MAX_SENTENCES = 2
HANGUP_AFTER_S = 3.0
SENTENCE = re.compile(r"(?<=[.?!])\s*(?=\S)")
UNSPEAKABLE = re.compile(r"[​-‏ - ⁠﻿�]")  # zero-width etc. made TTS say only "about"
# Questions/offers that belong to the company's assistant, never to the customer.
AGENT_LINE = re.compile(
    r"\b(?:where do you (?:\w+ )?(?:live|reside|stay)|how old are you|what(?:'s| is) your (?:age|name|budget|city)"
    r"|(?:may|can) i (?:have|know|ask) your|could you (?:tell me|share|confirm) your|do you have any (?:pre-?existing|existing)"
    r"|would you like (?:me to|a callback)|i(?:'ll| will) (?:schedule|arrange|book|set up)|our (?:advis|team)"
    r"|how (?:can|may) i (?:help|assist)|anything else i can|who (?:would|do) you (?:want|like) to (?:cover|insure)"
    r"|(?:which|what) city do you|how much would you like to spend"
    r"|assistant|garbled|as (?:the|a) customer|role-?play|\boutput\b)", re.I)  # out-of-character meta talk
CLOSING = re.compile(r"good ?bye|have a (?:good|great|nice) day|take care|ingat po|selamat beraktivitas|terima kasih atas "
                     r"waktunya|connecting you|ikokonekta|sambungkan|will call you|tatawag po|akan menghubungi", re.I)


def build_tts(chain: list[dict]):
    for v in chain:
        if v["provider"] == "azure" and os.getenv("AZURE_SPEECH_KEY"):
            return azure.TTS(voice=v["voice"], language=v.get("language"), speech_key=os.getenv("AZURE_SPEECH_KEY"),
                             speech_region=os.getenv("AZURE_SPEECH_REGION"))
        if v["provider"] == "deepgram" and os.getenv("DEEPGRAM_API_KEY"):
            return deepgram.TTS(model=v["voice"])
    raise RuntimeError("no TTS credentials for the sim caller (need AZURE_SPEECH_KEY or DEEPGRAM_API_KEY)")


class Caller(Agent):
    """No tools on purpose: an LLM hang-up tool made the caller end early or answer twice. Hang-up is rule-based."""

    def __init__(self, instructions: str, ctx: JobContext, probes: dict[int, str] | None = None) -> None:
        super().__init__(instructions=instructions)
        self._ctx = ctx
        self.probes = probes or {}  # reply number -> line appended to that reply (persona `probes:`)
        self.replies = 0
        self.heard: list[str] = []
        self.hanging_up = False
        self._hangup: asyncio.TimerHandle | None = None

    async def llm_node(self, chat_ctx, tools, model_settings):
        """LLM reply, then the persona's scripted probe for this reply number (if any): scenario coverage must not
        depend on the caller model remembering its instructions."""
        self.replies += 1
        async for chunk in self._guarded(chat_ctx, tools, model_settings):
            yield chunk
        if probe := self.probes.get(self.replies):
            logger.info("[sim] scripted probe: %s", probe)
            yield ChatChunk(id="probe", delta=ChoiceDelta(role="assistant", content=" " + probe))

    async def _guarded(self, chat_ctx, tools, model_settings):
        """Sentence-level guard: drops lines only the assistant would say and caps the reply at MAX_SENTENCES."""
        buf, kept, cid = "", 0, "caller"
        async for chunk in super().llm_node(chat_ctx, tools, model_settings):
            text = chunk.delta.content if getattr(chunk, "delta", None) else None
            if not text:
                continue
            cid, buf = chunk.id, buf + UNSPEAKABLE.sub("", text).replace("₹", "rupees ")
            *done, buf = SENTENCE.split(buf)
            for sent in done:
                if not any(c.isalnum() for c in sent):
                    continue  # ".." replies: nothing to say
                if AGENT_LINE.search(sent):
                    logger.info("[sim] dropped agent-like line: %s", sent.strip())
                    continue
                yield ChatChunk(id=cid, delta=ChoiceDelta(role="assistant", content=sent))
                kept += 1
                if kept >= MAX_SENTENCES:
                    return
        if any(c.isalnum() for c in buf) and not AGENT_LINE.search(buf) and (kept == 0 or len(buf.split()) >= 4):
            yield ChatChunk(id=cid, delta=ChoiceDelta(role="assistant", content=buf))

    def on_heard(self, text: str) -> None:
        """After a closing phrase, hang up once the agent has been quiet for HANGUP_AFTER_S (each new segment re-arms),
        so the goodbye is never cut mid-sentence."""
        self.heard.append(text)
        if not self.hanging_up and CLOSING.search(text):
            self.hanging_up = True
            logger.info("[sim] agent is closing the call; hanging up after its last words")
        if self.hanging_up:
            if self._hangup:
                self._hangup.cancel()
            self._hangup = asyncio.get_event_loop().call_later(
                HANGUP_AFTER_S, lambda: self._ctx.shutdown(reason="caller hung up"))


rtc_warmup.warm()
server = AgentServer(**rtc_warmup.server_kwargs())


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    pack = load_pack(meta.get("pack"))
    persona = yaml.safe_load((PERSONAS / pack.id / f"{meta.get('scenario', 'cooperative')}.yaml").read_text(encoding="utf-8"))
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.room.local_participant.set_attributes({"role": "customer", "persona": persona["name"]})
    bot = await wait_for_role(ctx.room, {"voice_agent"}, timeout=60)

    cfg = LLMConfig.from_env("SIM_")
    session = AgentSession(
        stt=build_stt(pack, override=persona.get("stt_provider")),
        llm=build_llm(cfg, temperature=0.3),
        tts=build_tts(persona["voice"]),
        vad=silero.VAD.load(min_silence_duration=0.6),
        # reply only after the agent has clearly finished (its TTS has short gaps between clauses); if the agent
        # starts talking again, drop our pending reply instead of queueing it (queued replies = double answers)
        turn_handling={"endpointing": {"mode": "fixed", "min_delay": 2.0, "max_delay": 4.0},
                       "interruption": {"enabled": True, "mode": "vad", "min_duration": 0.8,
                                        "resume_false_interruption": False},
                       "preemptive_generation": {"enabled": False}},
    )
    probes = {int(k): v for k, v in (persona.get("probes") or {}).items()}
    caller = Caller(CALLER_RULES + "\n" + persona["instructions"], ctx, probes)

    @session.on("conversation_item_added")
    def _log_item(ev) -> None:
        text = (getattr(ev.item, "text_content", None) or "").strip()
        if text and ev.item.role == "user":
            logger.info("[sim] heard agent: %s", text)
            caller.on_heard(text)
        elif text and ev.item.role == "assistant":
            logger.info("[sim] caller said: %s", text)

    await session.start(caller, room=ctx.room,
                        room_options=room_io.RoomOptions(participant_identity=bot.identity, participant_kinds=[KIND_AGENT],
                                                         close_on_disconnect=True))
    max_s = float(persona.get("max_minutes", 4)) * 60
    asyncio.get_event_loop().call_later(max_s, lambda: ctx.shutdown(reason="sim max duration"))


if __name__ == "__main__":
    from livekit.agents import cli
    cli.run_app(server)
