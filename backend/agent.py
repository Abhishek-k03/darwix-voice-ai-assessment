"""Voice agent worker (Q1 + Q3). One worker, many packs (market/use case) selected per call by dispatch metadata.

Pipeline (unchanged core from the base repo): Silero VAD -> STT(pack) -> SemanticTurnCoordinator (manual turns,
backchannel/pause handling, barge-in) -> LLM -> persistent streaming TTS worker -> own LiveKit audio track.
Added: per-turn [extraction || KB retrieval] -> deterministic FlowEngine -> directive injected before the LLM reply,
business actions (CRM), human escalation into the same room, call recording, live state over data channels.

Run: uv run python -m livekit.agents start agent.py --dev
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Annotated

from dotenv import find_dotenv, load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    RunContext,
    StopResponse,
    function_tool,
)
from livekit.agents.llm import ChatChunk, ChoiceDelta
from livekit.agents.voice import room_io
from livekit.plugins import silero

import rag
import rtc_warmup
from livekit_audio_publisher import PlaybackTracker, publish_audio_track
from llm_provider import build_llm
from llm_stream import LLMConfig
from packs import Pack, load_pack
from roles import KIND_AGENT, KIND_SIP, KIND_STANDARD, role_of, wait_for_role
from stt_provider import build_stt
from stt_provider import describe as describe_stt
from tts_streamer import SHUTDOWN, TURN_END, TTSConfig, stream_tts_worker
from turn_arbiter import RollingTranscriptBuffer, classify_turn_intent
from turn_arbiter import _get_default_client as arbiter_client
from voice import actions
from voice.engine import FlowEngine
from voice.extract import _get_client as extract_client
from voice.extract import extract_turn
from voice.quick import resolve as quick_resolve
from voice.recorder import CallRecorder
from voice.state import CallState

load_dotenv(find_dotenv())
os.environ.setdefault("LIVEKIT_AGENT_NAME", "voice-agent")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nexus.agent")

IDLE_TIMEOUT_SECONDS: float = float(os.getenv("NEXUS_IDLE_TIMEOUT_SECONDS", "45"))
ADVISOR_WAIT_S = float(os.getenv("ADVISOR_WAIT_S", "90"))


# ── Barge-in interrupt controller ─────────────────────────────────────────────

class InterruptController:
    """trigger() sets interrupt_event: the TTS worker purges its queues, the publisher clears the WebRTC playout
    buffer, registered tasks are cancelled and session.interrupt() flushes the LLM generation."""

    def __init__(self, session: AgentSession, busy=None) -> None:
        self._session = session
        self._busy = busy or (lambda: True)
        self.interrupt_event: asyncio.Event = asyncio.Event()
        self._active_tasks: set[asyncio.Task] = set()
        self._watcher_task: asyncio.Task | None = None

    def start(self) -> None:
        self._watcher_task = asyncio.ensure_future(self._interrupt_watcher())

    def register_task(self, task: asyncio.Task) -> asyncio.Task:
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        return task

    def trigger(self) -> None:
        """Only when the bot is actually talking: an idle interrupt made the TTS worker reconnect every turn."""
        if not self.interrupt_event.is_set() and self._busy():
            logger.info("[barge-in] complete turn confirmed -> firing interrupt_event")
            self.interrupt_event.set()

    async def _interrupt_watcher(self) -> None:
        while True:
            try:
                await self.interrupt_event.wait()
                self.interrupt_event.clear()
                for task in list(self._active_tasks):
                    if not task.done():
                        task.cancel()
                try:
                    self._session.interrupt()
                except Exception as exc:
                    logger.warning("[barge-in] buffer flush error: %s", exc)
            except asyncio.CancelledError:
                break

    async def stop(self) -> None:
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watcher_task


# ── Semantic turn-taking arbiter ──────────────────────────────────────────────

BASE_SILENCE_TIMEOUT_S = 0.4
EXTENDED_SILENCE_TIMEOUT_S = 1.2
PAUSE_EXTENSION_DELTA_S = EXTENDED_SILENCE_TIMEOUT_S - BASE_SILENCE_TIMEOUT_S
TRANSCRIPT_WINDOW_SECONDS = 5.0
EMPTY_TRANSCRIPT_WAIT_S = 0.6
JUNK = re.compile("[*_#`…​‌‍﻿\xa0]+")
INCOMPLETE_HOLD_S = 1.0
YES_NO_HOLD_S = 0.4
QUICK_ANSWERS = os.getenv("QUICK_ANSWERS", "on").lower() != "off"
AGENT_BUSY_TAIL_S = 3.0
REPROMPT_AFTER_S = float(os.getenv("REPROMPT_AFTER_S", "10"))
MAX_REPROMPTS = 2


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


class SemanticTurnCoordinator:
    """Sits between VAD and the barge-in kill switch: on VAD silence it classifies the rolling transcript —
    backchannel -> discard (bot keeps talking); mid-thought pause -> wait 400ms->1200ms; complete -> barge-in +
    commit the turn to the LLM. A new VAD onset cancels any pending decision. `paused()` (human advisor took over)
    suppresses commits; `lexicon` selects the market's backchannel/connector words (Q3)."""

    def __init__(self, session: AgentSession, interrupt_ctrl: InterruptController, *,
                 paused=None, agent_speaking=None, yes_no_expected=None, lexicon: str = "en") -> None:
        self._session = session
        self._interrupt_ctrl = interrupt_ctrl
        self._paused = paused or (lambda: False)
        self._agent_speaking = agent_speaking or (lambda: True)
        self._yes_no_expected = yes_no_expected or (lambda: False)
        self.lexicon = lexicon
        self.buffer = RollingTranscriptBuffer(window_seconds=TRANSCRIPT_WINDOW_SECONDS)
        self._pending_task: asyncio.Task | None = None
        self._user_speaking = False
        self._committed, self._committed_at = "", 0.0

    def on_transcript(self, transcript: str, *, is_final: bool) -> None:
        if is_final and time.monotonic() - self._committed_at < 3 and _norm(transcript) in self._committed:
            return  # the STT final of words already committed from their interim
        self.buffer.add(transcript, is_final=is_final)
        if is_final and transcript.strip() and not self._user_speaking and not self._pending():
            self._pending_task = asyncio.ensure_future(self._decide())  # final landed after the VAD-end decision

    def on_speech_started(self) -> None:
        self._user_speaking = True
        self._cancel_pending()

    def on_speech_ended(self) -> None:
        self._user_speaking = False
        self._cancel_pending()
        self._pending_task = asyncio.ensure_future(self._decide())

    def _pending(self) -> bool:
        return bool(self._pending_task and not self._pending_task.done())

    def _cancel_pending(self) -> None:
        if self._pending():
            self._pending_task.cancel()

    async def _decide(self) -> None:
        try:
            transcript = self.buffer.window_text()
            if not transcript.strip():
                await asyncio.sleep(EMPTY_TRANSCRIPT_WAIT_S)  # STT final may lag VAD; noise never commits
                transcript = self.buffer.window_text()
                if not transcript.strip():
                    return  # no clear_user_turn(): it restarts the STT stream and drops a short answer in flight
            extra = {"lexicon": self.lexicon} if self.lexicon != "en" else {}
            result = await classify_turn_intent(transcript, **extra)
            logger.info("[turn-arbiter] transcript=%r complete=%s backchannel=%s extend=%s", transcript,
                        result.is_complete_turn, result.is_backchannel, result.requires_pause_extension)
            if self._paused() or (result.is_backchannel and self._agent_speaking()):
                self.buffer.clear()
                self._session.clear_user_turn()  # "uh-huh" over the bot's speech: keep talking
                return
            if result.is_backchannel and self._yes_no_expected():
                await asyncio.sleep(YES_NO_HOLD_S)  # the bot asked a yes/no question: "Sure." is most likely the answer
            elif result.requires_pause_extension or result.is_backchannel:
                # with the bot silent, "Sure." is an answer, though maybe the start of "Sure, I have a minute"
                await asyncio.sleep(PAUSE_EXTENSION_DELTA_S)
            elif not result.is_complete_turn:
                await asyncio.sleep(INCOMPLETE_HOLD_S)  # new speech cancels this; the buffer keeps the first half
            await asyncio.shield(self._commit_turn())  # half a commit (interrupted, never committed) loses the turn
        except asyncio.CancelledError:
            raise

    async def _commit_turn(self) -> None:
        self._committed, self._committed_at = _norm(self.buffer.window_text()), time.monotonic()
        self.buffer.clear()  # first: a decision racing this one must not see (and commit) the same phrase
        self._interrupt_ctrl.trigger()
        with contextlib.suppress(Exception):
            await self._session.interrupt()
        self._session.commit_user_turn(transcript_timeout=2.0)

    async def aclose(self) -> None:
        self._cancel_pending()
        if self._pending_task:
            with contextlib.suppress(asyncio.CancelledError):
                await self._pending_task


# ── Idle watchdog (FinOps) ────────────────────────────────────────────────────

class IdleWatchdog:
    """Disconnects after IDLE_TIMEOUT_SECONDS without user or agent activity (ghost sessions burn STT cost)."""

    def __init__(self, ctx: JobContext, timeout: float = IDLE_TIMEOUT_SECONDS, on_timeout=None) -> None:
        self._ctx = ctx
        self._timeout = timeout
        self._on_timeout = on_timeout
        self._activity_event = asyncio.Event()
        self._watchdog_task: asyncio.Task | None = None
        self._last_activity = time.monotonic()

    def start(self) -> None:
        self._activity_event.set()
        self._watchdog_task = asyncio.ensure_future(self._watch())

    def pulse(self, reason: str = "") -> None:
        self._last_activity = time.monotonic()
        self._activity_event.set()

    async def _watch(self) -> None:
        while True:
            self._activity_event.clear()
            try:
                await asyncio.wait_for(self._activity_event.wait(), timeout=self._timeout)
            except asyncio.TimeoutError:
                logger.warning("[watchdog] %.1fs idle — ending call", time.monotonic() - self._last_activity)
                if self._on_timeout:
                    await self._on_timeout()
                break

    async def stop(self) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task


# ── Per-call controller ───────────────────────────────────────────────────────

class CallController:
    def __init__(self, ctx: JobContext, pack: Pack, state: CallState, recorder: CallRecorder,
                 tts_text_queue: asyncio.Queue, tts_audio_queue: asyncio.Queue, tracker: PlaybackTracker) -> None:
        self.ctx, self.pack, self.state, self.recorder = ctx, pack, state, recorder
        self.engine = FlowEngine(pack, state)
        self.tts_text_queue, self.tts_audio_queue, self.tracker = tts_text_queue, tts_audio_queue, tracker
        self.session: AgentSession | None = None
        self.last_agent_text = ""
        self.end_after_reply = False
        self.pending_citations: list[str] = []
        self.meta: dict = {}
        self._ending = False
        self._finalized = False
        self._advisor_timer: asyncio.Task | None = None
        self.last_user_activity = time.monotonic()
        self.reprompts = 0
        self.last_gen_at = 0.0
        self.thinking_since = 0.0
        self.typed = False

    def expects_yes_no(self) -> bool:
        spec = self.pack.field(self.state.awaiting or "")
        return bool(spec and spec.quick in ("yesno", "consent", "confirm"))

    def agent_speaking(self) -> bool:
        return self.tracker.speaking() or not self.tts_audio_queue.empty() or not self.tts_text_queue.empty()

    def agent_busy(self) -> bool:
        return self.agent_speaking() or time.monotonic() - self.last_gen_at < AGENT_BUSY_TAIL_S

    def user_active(self) -> None:
        self.last_user_activity = time.monotonic()
        self.reprompts = 0

    async def reprompt_loop(self) -> None:
        """Dead air after the bot finished speaking -> re-prompt in the pack's language (max twice)."""
        while not self._ending:
            await asyncio.sleep(1.0)
            s = self.state
            if s.handoff_active or s.end_requested or self.reprompts >= MAX_REPROMPTS or not self.tracker.last_frame_at:
                continue
            if self.tracker.speaking() or not self.tts_audio_queue.empty() or not self.tts_text_queue.empty():
                continue
            if self.session and self.session.user_state == "speaking":
                continue                                    # only a transcript counts as 'heard', not bare VAD
            if time.monotonic() - max(self.last_user_activity, self.tracker.last_frame_at) > REPROMPT_AFTER_S:
                self.reprompts += 1
                await self.speak(self.pack.line("reprompt", **self.engine._fmt()), kind="reprompt")

    async def state_loop(self) -> None:
        """Tells the UI what the agent is doing (listening / thinking / speaking) whenever it changes."""
        prev, hold = None, 0.0
        while not self._ending:
            await asyncio.sleep(0.1)
            now = time.monotonic()
            if self.agent_speaking():
                hold = now + 0.9                     # gaps between synthesized clauses are not silence
            if now < hold:
                self.thinking_since, st = 0.0, "speaking"
            elif self.thinking_since and time.monotonic() - self.thinking_since < 12:
                st = "thinking"
            else:
                st = "listening"
            if st != prev:
                prev = st
                await self.publish("agent-state", {"state": st})

    async def on_typed(self, sess, text: str) -> None:
        """A typed message takes the same engine path as a spoken turn (the default text callback would skip it)."""
        class _Note:
            note = ""

            def add_message(self, *, role: str, content: str) -> None:
                self.note = content

        note = _Note()
        async with sess._claim_user_turn():
            await sess.interrupt()
            self.user_active()
            self.typed = True
            try:
                await self.on_user_turn(note, SimpleNamespace(text_content=text))
            except StopResponse:
                return
            sess.generate_reply(user_input=text, instructions=note.note)

    async def publish(self, topic: str, payload: dict) -> None:
        with contextlib.suppress(Exception):
            await self.ctx.room.local_participant.publish_data(
                json.dumps(payload, default=str, ensure_ascii=False).encode(), topic=topic, reliable=True)

    def on_agent_text(self, text: str, **meta) -> None:
        text = text.strip()
        if not text:
            return
        self.last_agent_text = text
        self.recorder.add_turn("agent", text, **meta)
        asyncio.ensure_future(self.publish("transcript", {"role": "agent", "text": text, "t": self.recorder.now(), **meta}))

    async def speak(self, text: str, kind: str = "script") -> None:
        """Pre-approved lines bypass the LLM: chat history via session.say, audio via our TTS worker."""
        self.session.say(text, allow_interruptions=True, add_to_chat_ctx=True)
        self.state.awaiting_exact = kind in ("quick", "greeting")  # fixed wording: the asked field is certain
        self.last_gen_at = time.monotonic()
        await self.tts_text_queue.put(text)
        await self.tts_text_queue.put(TURN_END)
        self.on_agent_text(text, kind=kind)

    async def _merge_late(self, task: asyncio.Future) -> None:
        try:
            late = await asyncio.wait_for(task, timeout=8)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[extract] late result lost: %r", exc)
            return
        self.state.log("late_extract", updates=self.engine.merge_updates(late.get("updates", [])))
        await self.publish("call-state", self.state_payload())

    def state_payload(self) -> dict:
        s = self.state
        return {"stage": s.stage, "fields": s.known(), "missing": [f.name for f in self.engine._missing()],
                "conflicts": [c.__dict__ for c in s.pending_conflicts], "eligibility": s.eligibility,
                "escalated": s.escalated, "handoff": s.handoff_active, "callback": s.callback, "outcome": s.outcome,
                "objections": s.objections, "turn": s.turn}

    async def on_user_turn(self, turn_ctx, new_message) -> None:
        text = (new_message.text_content or "").strip()
        if not text:
            raise StopResponse()
        self.recorder.add_turn("customer", text)
        await self.publish("transcript", {"role": "customer", "text": text, "t": self.recorder.now(),
                                          **({"typed": True} if self.typed else {})})
        self.typed = False
        if self.state.handoff_active or self._ending:
            raise StopResponse()
        self.thinking_since = time.monotonic()

        t0 = time.perf_counter()
        quick = quick_resolve(self.pack, self.state, self.last_agent_text, text) if QUICK_ANSWERS else None
        if quick:  # a plain answer to the field just asked: no extraction LLM, no KB lookup
            extraction, kb = quick, {"status": "skipped", "hits": [], "client_latency_ms": 0.0}
        else:
            extraction, kb = await asyncio.gather(
                extract_turn(self.pack, self.state, self.last_agent_text, text),
                rag.search_turn(text, self.pack.market, k=3),
            )
        late = extraction.pop("late", None)
        if late:
            asyncio.ensure_future(self._merge_late(late))
        directive = self.engine.apply(extraction, kb, text)
        pre_llm_ms = round((time.perf_counter() - t0) * 1000, 1)
        self.state.log("trace", extract_ms=extraction.get("latency_ms"), kb_ms=kb.get("client_latency_ms"),
                       kb_status=kb.get("status"), pre_llm_ms=pre_llm_ms, intents=extraction.get("intents"),
                       quick=bool(quick), fast_reply=bool(directive.quick_reply))
        await self.publish("call-state", self.state_payload())
        await self.publish("rag-status", {"type": "rag_search", "query": text, "status": kb.get("status"),
                                          "used": directive.knowledge_used,
                                          "hits": [{"record_id": h["record_id"], "title": h["title"], "citation": h["citation"],
                                                    "dense": h.get("dense"), "score": h.get("score")} for h in kb.get("hits", [])]})
        for name, args in directive.actions:
            asyncio.ensure_future(self.run_action(name, args))
        self.pending_citations = directive.knowledge_used

        if directive.silent:
            self.thinking_since = 0.0
            raise StopResponse()
        if directive.quick_reply and not directive.say_exactly:
            await self.speak(directive.quick_reply, kind="quick")
            raise StopResponse()
        if directive.say_exactly:
            await self.speak(directive.say_exactly)
            if directive.end_call:
                asyncio.ensure_future(self.end_call("script_close"))
            raise StopResponse()
        turn_ctx.add_message(role="system", content=directive.note)
        self.end_after_reply = directive.end_call

    def on_reply_done(self, text: str) -> None:
        self.state.awaiting_exact = False  # LLM wording: a short answer is mapped only if the question has the field's cues
        self.on_agent_text(text, citations=self.pending_citations, kind="llm")
        self.pending_citations = []
        if self.end_after_reply:
            asyncio.ensure_future(self.end_call("flow_complete"))

    async def run_action(self, name: str, args: dict) -> None:
        s, p = self.state, self.pack
        if name == "escalate":
            res = await actions.escalate(s, p, args.get("reason", ""))
            join = (res or {}).get("human_join") or {}
            await self.publish("escalation", {"reason": args.get("reason"), "join_url": join.get("join_url"),
                                              "escalation_id": (res or {}).get("id")})
            self._advisor_timer = asyncio.ensure_future(self._advisor_timeout())
        elif name == "callback":
            await actions.schedule_callback(s, p, args["when"])
        elif name == "dnc":
            await actions.mark_dnc(s, p)

    async def _advisor_timeout(self) -> None:
        await asyncio.sleep(ADVISOR_WAIT_S)
        if not self.state.handoff_active and not self._ending:
            self.state.callback = {"when": "within two hours (priority)"}
            await actions.schedule_callback(self.state, self.pack, "within two hours (priority)", "escalation fallback")
            await self.speak(self.pack.line("escalation_unavailable"))
            await self.end_call("advisor_unavailable")

    def on_participant(self, p: rtc.RemoteParticipant) -> None:
        if role_of(p) == "advisor":
            self.state.handoff_active = True
            self.state.log("advisor_joined", identity=p.identity)
            if self._advisor_timer:
                self._advisor_timer.cancel()
            asyncio.ensure_future(self.publish("call-state", self.state_payload()))

    async def _wait_goodbye_spoken(self, start_timeout_s: float = 6.0) -> None:
        """The goodbye is queued as text before any of its audio exists, so 'silent' right now means 'not started':
        wait for audio newer than the last text, then for the text queue to drain and the line to go quiet."""
        deadline = time.monotonic() + start_timeout_s
        while self.tracker.last_frame_at < self.last_gen_at and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        deadline = time.monotonic() + 20
        while not self.tts_text_queue.empty() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        await self.tracker.wait_idle(self.tts_audio_queue, silence_s=1.2, timeout_s=max(1.0, deadline - time.monotonic()))

    async def end_call(self, reason: str) -> None:
        if self._ending:
            return
        self._ending = True
        await self._wait_goodbye_spoken()
        await self.finalize(reason)
        await asyncio.sleep(0.5)
        self.ctx.shutdown(reason=f"call ended: {reason}")

    async def finalize(self, reason: str = "") -> None:
        if self._finalized:
            return
        self._finalized = True
        s = self.state
        if not s.outcome:
            s.outcome = "qualified" if (s.eligibility or {}).get("eligible") else "incomplete"
        await actions.create_lead(s, self.pack)
        result = {**actions.summary(s, self.pack), "lead_id": s.lead_id, "end_reason": reason, **self.meta,
                  "stt": describe_stt(self.pack), "events": s.events}
        await asyncio.to_thread(self.recorder.finalize, result)
        await self.publish("call-ended", {"outcome": s.outcome, "grade": result.get("grade"), "lead_id": s.lead_id})


# ── Agent ─────────────────────────────────────────────────────────────────────

class NexusAgent(Agent):
    """llm_node forwards each content delta to the persistent TTS worker (clause-level synthesis) and yields the
    chunks unchanged, so AgentSession's tool calling and history work as usual. on_user_turn_completed runs the
    extraction/retrieval/engine step and injects the directive."""

    def __init__(self, *, instructions: str, tts_text_queue: asyncio.Queue, controller: CallController) -> None:
        super().__init__(instructions=instructions)
        self._tts_text_queue = tts_text_queue
        self._ctrl = controller

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        await self._ctrl.on_user_turn(turn_ctx, new_message)

    async def llm_node(self, chat_ctx, tools, model_settings):
        """One question per reply: text after the first '?' is the model answering for the customer and asking again."""
        parts: list[str] = []
        asked, junk = False, 0
        async for chunk in super().llm_node(chat_ctx, tools, model_settings):
            text = chunk.delta.content if chunk.delta else None
            if text:
                clean = JUNK.sub("", text)
                junk = junk + 1 if text != clean and not any(c.isalnum() for c in clean) else 0
                if junk >= 3:
                    break                       # degenerate output ("***…"): cut it off, never speak it
                if clean != text:
                    if not clean:
                        continue
                    text = clean
                    chunk = ChatChunk(id=chunk.id, delta=ChoiceDelta(role="assistant", content=text))
                if asked:
                    if any(c.isalnum() for c in text):
                        break
                    continue
                q = text.find("?")
                if q >= 0:
                    asked = True
                    if any(c.isalnum() for c in text[q + 1:]):
                        text = text[:q + 1]
                        chunk = ChatChunk(id=chunk.id, delta=ChoiceDelta(role="assistant", content=text))
                self._ctrl.last_gen_at = time.monotonic()
                parts.append(text)
                await self._tts_text_queue.put(text)
            yield chunk
        await self._tts_text_queue.put(TURN_END)
        if parts:
            self._ctrl.on_reply_done("".join(parts))

    @function_tool(description="Search the company knowledge base for product, policy, claims or objection-handling "
                               "information when the provided KNOWLEDGE does not cover the customer's question.")
    async def search_knowledge_base(self, context: RunContext,
                                    query: Annotated[str, "Search query in the customer's language"]) -> str:
        res = await rag.search(query, self._ctrl.pack.market, k=3)
        self._ctrl.pending_citations += [h["record_id"] for h in res.get("hits", [])[:3] if res.get("status") == "ok"]
        return res.get("llm_context", "NO_RELEVANT_INFO")

    @function_tool(description="Schedule a callback from a licensed advisor when the customer agrees and gives a time.")
    async def schedule_advisor_callback(self, context: RunContext,
                                        when: Annotated[str, "When to call back, as the customer said it"]) -> str:
        s = self._ctrl.state
        if not s.callback:
            s.callback = {"when": when}
            s.outcome = s.outcome or "callback_scheduled"
            await actions.schedule_callback(s, self._ctrl.pack, when)
        self._ctrl.end_after_reply = True
        return f"Callback scheduled for {when}. Confirm it to the customer and close politely."

    @function_tool(description="Connect the customer to a human licensed advisor (customer asked for a person, is "
                               "upset, or the case needs an underwriter).")
    async def request_human_advisor(self, context: RunContext, reason: Annotated[str, "Why"]) -> str:
        if not self._ctrl.state.escalated:
            self._ctrl.state.escalated, self._ctrl.state.outcome = True, "escalated"
            await self._ctrl.run_action("escalate", {"reason": reason})
        return f"Escalation started. Say: {self._ctrl.pack.line('escalation')}"


# ── Worker ────────────────────────────────────────────────────────────────────

def prewarm(proc: JobProcess) -> None:
    rtc_warmup.warm()
    proc.userdata["vad"] = silero.VAD.load(activation_threshold=0.35, min_silence_duration=BASE_SILENCE_TIMEOUT_S)


async def _warm_clients() -> None:
    """Each per-loop HTTP/LLM client costs ~250-450ms of blocking TLS setup: pay it before the customer speaks."""
    rag._http()
    extract_client()
    await arbiter_client()


rtc_warmup.warm()
server = AgentServer(setup_fnc=prewarm, **rtc_warmup.server_kwargs())


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    pack = load_pack(meta.get("pack"))
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.room.local_participant.set_attributes({"role": "voice_agent", "pack": pack.id})
    await _warm_clients()
    customer = await wait_for_role(ctx.room, {"customer"}, timeout=180)
    logger.info("call %s pack=%s customer=%s", meta.get("call_id"), pack.id, customer.identity)

    state = CallState(pack_id=pack.id, call_id=meta.get("call_id") or ctx.room.name[-10:], room=ctx.room.name)
    customer_id = meta.get("customer_id") or pack.demo_customer
    if customer_id:
        state.customer = await asyncio.to_thread(_customer, customer_id)
    label = f"{pack.id}_{meta.get('scenario') or meta.get('mode', 'web')}"
    recorder = CallRecorder(state.call_id, label, sample_rate=int(os.getenv("TTS_SAMPLE_RATE", "24000")))
    tts_config = TTSConfig.from_chain(list(pack.tts))
    logger.info("tts=%s/%s fallback=%s stt=%s", tts_config.provider, tts_config.voice, tts_config.fallback_provider,
                describe_stt(pack))

    llm_model = pack.llm.get("model") or LLMConfig.from_env().model
    session = AgentSession(
        stt=build_stt(pack),
        llm=build_llm(replace(LLMConfig.from_env(), model=llm_model)),
        tts=None,
        vad=ctx.proc.userdata["vad"],
        turn_handling={"turn_detection": "manual"},
    )
    tts_text_queue: asyncio.Queue = asyncio.Queue()
    tts_audio_queue: asyncio.Queue = asyncio.Queue()
    tracker = PlaybackTracker()
    ctrl = CallController(ctx, pack, state, recorder, tts_text_queue, tts_audio_queue, tracker)
    ctrl.session = session
    ctrl.meta = {"mode": meta.get("mode"), "scenario": meta.get("scenario"), "tts": tts_config.provider,
                 "tts_voice": tts_config.voice, "llm": llm_model}

    interrupt_ctrl = InterruptController(session, busy=ctrl.agent_busy)
    watchdog = IdleWatchdog(ctx, on_timeout=lambda: ctrl.end_call("idle_timeout"))
    turn_coordinator = SemanticTurnCoordinator(session, interrupt_ctrl, paused=lambda: state.handoff_active,
                                               agent_speaking=ctrl.agent_speaking, yes_no_expected=ctrl.expects_yes_no,
                                               lexicon=pack.turn_lexicon)

    tts_worker_task = asyncio.ensure_future(
        stream_tts_worker(tts_text_queue, tts_audio_queue, interrupt_ctrl.interrupt_event, config=tts_config))
    audio_publish_task = await publish_audio_track(
        ctx.room, tts_audio_queue, interrupt_ctrl.interrupt_event, sample_rate=tts_config.sample_rate,
        on_frame=recorder.agent_frame, tracker=tracker)

    @session.on("user_state_changed")
    def on_user_state(ev) -> None:
        if ev.new_state == "speaking":
            turn_coordinator.on_speech_started()
            watchdog.pulse("user_speech_started")
        elif ev.new_state == "listening":
            turn_coordinator.on_speech_ended()
            watchdog.pulse("user_speech_ended")

    @session.on("user_input_transcribed")
    def on_user_input(ev) -> None:
        turn_coordinator.on_transcript(ev.transcript, is_final=ev.is_final)
        watchdog.pulse("transcript")
        ctrl.user_active()

    @session.on("agent_state_changed")
    def on_state(ev) -> None:
        watchdog.pulse("agent_state")

    @session.on("metrics_collected")
    def on_metrics(ev) -> None:
        m = ev.metrics
        if getattr(m, "ttft", None) is not None:
            state.log("llm_metrics", ttft_ms=round(m.ttft * 1000, 1), duration_ms=round(getattr(m, "duration", 0) * 1000, 1))

    @session.on("error")
    def on_error(ev) -> None:
        logger.error("session error: %s", ev.error)

    @ctx.room.on("track_subscribed")
    def on_track(track: rtc.Track, _pub, participant: rtc.RemoteParticipant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity == customer.identity:
            asyncio.ensure_future(recorder.capture_customer(track))

    @ctx.room.on("participant_connected")
    def on_join(p: rtc.RemoteParticipant) -> None:
        ctrl.on_participant(p)

    @ctx.room.on("participant_disconnected")
    def on_leave(p: rtc.RemoteParticipant) -> None:
        if p.identity == customer.identity:
            asyncio.ensure_future(ctrl.end_call("customer_hung_up"))

    for pub in customer.track_publications.values():
        if pub.track and pub.track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.ensure_future(recorder.capture_customer(pub.track))

    async def _cleanup(*_a) -> None:
        await ctrl.finalize("shutdown")
        await turn_coordinator.aclose()
        await interrupt_ctrl.stop()
        await watchdog.stop()
        await tts_text_queue.put(SHUTDOWN)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(tts_worker_task, timeout=3)
        await tts_audio_queue.put(SHUTDOWN)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(audio_publish_task, timeout=3)

    ctx.add_shutdown_callback(_cleanup)
    interrupt_ctrl.start()
    watchdog.start()

    agent = NexusAgent(instructions=pack.prompt.format(persona=pack.persona, company=pack.company),
                       tts_text_queue=tts_text_queue, controller=ctrl)
    await session.start(agent, room=ctx.room, room_options=room_io.RoomOptions(
        participant_identity=customer.identity, participant_kinds=[KIND_STANDARD, KIND_SIP, KIND_AGENT],
        audio_output=False, close_on_disconnect=False,
        text_input=room_io.TextInputOptions(text_input_cb=lambda sess, ev: ctrl.on_typed(sess, ev.text))))
    c = state.customer or {}
    state.awaiting = pack.greeting_awaits or None
    await ctrl.speak(pack.line("greeting", salutation=pack.salutation(), title=c.get("title", ""), name=c.get("name", "")),
                     kind="greeting")
    reprompt_task = asyncio.ensure_future(ctrl.reprompt_loop())
    state_task = asyncio.ensure_future(ctrl.state_loop())

    async def _stop_reprompt(*_a) -> None:
        reprompt_task.cancel()
        state_task.cancel()

    ctx.add_shutdown_callback(_stop_reprompt)


def _customer(cid: str) -> dict:
    import crm
    return crm.customer(cid) or {}


if __name__ == "__main__":
    from livekit.agents import cli
    cli.run_app(server)
