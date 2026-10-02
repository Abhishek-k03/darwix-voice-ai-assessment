"""Per-turn structured extraction with a fast small LLM (JSON mode, hard timeout, never raises).

Runs before the main LLM reply, in parallel with KB retrieval, so the flow engine works on fresh state and the
main model only has to speak. On timeout/error the turn proceeds with no updates (the transcript still carries it).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from openai import AsyncOpenAI

from llm_stream import LLMConfig, build_client, create_completion
from packs import Pack

from .state import CallState

logger = logging.getLogger("voice.extract")

INTENTS = ["answer", "question", "objection", "out_of_scope", "human_request", "callback_request", "dnc",
           "not_interested", "busy", "greeting", "goodbye", "other"]
TIMEOUT_S = float(os.getenv("EXTRACT_TIMEOUT_S", "1.5"))

_clients: dict[int, AsyncOpenAI] = {}


def _get_client() -> tuple[AsyncOpenAI, LLMConfig]:
    """One client per event loop (each LiveKit job thread has its own loop)."""
    cfg = LLMConfig.from_env("FAST_")
    key = id(asyncio.get_running_loop())
    if key not in _clients:
        _clients[key] = build_client(cfg)
    return _clients[key], cfg


def _schema(pack: Pack) -> str:
    lines = []
    for f in pack.fields:
        allowed = f" (one of: {', '.join(f.values)})" if f.values else ""
        lines.append(f'- {f.name} [{f.type}]{allowed}: {f.description or f.ask}')
    return "\n".join(lines)


def build_prompt(pack: Pack, state: CallState, agent_said: str, customer_said: str) -> list[dict]:
    system = (
        "You extract structured data from one turn of a phone call between an AI agent and a customer. "
        "Reply with ONLY a JSON object, no prose.\n\n"
        f"Fields you may fill:\n{_schema(pack)}\n\n"
        f"Intents: {', '.join(INTENTS)}.\n"
        "Rules:\n"
        "- Extract only what the customer states or confirms in THIS turn. Do not invent values.\n"
        "- The text comes from speech recognition: '?' is often missing and words can be misheard. A turn can answer\n"
        "  AND ask (e.g. '31 is maternity cover two' = age 31 + question 'is maternity covered too'); add 'question'.\n"
        "- Short answers ('yes', 'no', a number) answer the agent's last question; map them to that field.\n"
        "- correction=true only if the customer explicitly corrects an earlier value or answers a reconfirmation.\n"
        f"- {pack.persona} is the AGENT's name: never record it as the customer's name, unless the agent just asked for\n"
        "  their name and they answer with exactly that.\n"
        "- outside_market=true only when the customer says they live outside India (a foreign city, state or country,\n"
        "  e.g. Oklahoma, London, Canada). Indian cities and misheard words are false.\n"
        "- intents is a list; human_request = wants a human/advisor/agent now; dnc = do not call again;\n"
        "  callback_request = wants to be called later; busy = not a good time now; question = asks about plans,\n"
        "  policy, claims or the process; objection = pushback (price, trust, already insured, needs to discuss);\n"
        "  goodbye = the customer is ending the call ('thanks, have a good day', 'bye', 'that's all').\n"
        "- objection: short label (e.g. too_expensive, has_employer_cover, needs_family_discussion, trust, claims_rejected,\n"
        "  pre_existing_rejection, think_about_it) or null.\n"
        "- sentiment from -1 (angry/frustrated) to 1 (happy).\n"
        f"{pack.extraction_hints}\n\n"
        'Format: {"updates":[{"field":"age","value":34,"confidence":0.9,"correction":false}],'
        '"intents":["answer"],"objection":null,"sentiment":0.2,"outside_market":false}'
    )
    user = (f"Known so far: {json.dumps(state.known(), ensure_ascii=False)}\n"
            f"Agent's last utterance: {agent_said or '(call start)'}\n"
            f"Customer: {customer_said}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


EMPTY = {"updates": [], "intents": ["other"], "objection": None, "sentiment": 0.0, "outside_market": False}


async def _call(messages: list[dict]) -> dict:
    client, cfg = _get_client()
    resp = await create_completion(client, cfg, messages=messages, temperature=0, max_tokens=300,
                                   response_format={"type": "json_object"})
    data = json.loads(resp.choices[0].message.content or "{}")
    out = {**EMPTY, **{k: v for k, v in data.items() if k in EMPTY}}
    out["intents"] = [i for i in out.get("intents") or [] if i in INTENTS] or ["other"]
    out["updates"] = [u for u in out.get("updates") or [] if isinstance(u, dict) and "field" in u]
    for u in list(out["updates"]):               # the model sometimes files the flag as a pseudo-field
        if u["field"] == "outside_market":
            out["outside_market"] = bool(u.get("value"))
            out["updates"].remove(u)
    out["outside_market"] = out.get("outside_market") is True
    return out


async def extract_turn(pack: Pack, state: CallState, agent_said: str, customer_said: str) -> dict:
    """On timeout the call keeps running and returns EMPTY + `late` (the still-running task) so the caller can merge
    the fields when they arrive instead of losing an answer to a provider latency spike."""
    t0 = time.perf_counter()
    task = asyncio.ensure_future(_call(build_prompt(pack, state, agent_said, customer_said)))
    try:
        out = await asyncio.wait_for(asyncio.shield(task), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("[extract] slower than %.1fs, merging late", TIMEOUT_S)
        out = dict(EMPTY, error="timeout", late=task)
    except Exception as exc:  # noqa: BLE001 — provider errors must never stall the call
        logger.warning("[extract] skipped: %s", exc)
        out = dict(EMPTY, error=str(exc))
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out
