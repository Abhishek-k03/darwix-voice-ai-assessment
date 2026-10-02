"""
Builds the LiveKit AgentSession LLM plugin from the same env-driven
LLMConfig used by the raw streaming client in llm_stream.py, so the live
voice pipeline and the standalone benchmark/SSE paths always target the
same inference provider — no hardcoded provider plugin (e.g. groq.LLM)
baked into the worker.
"""

from __future__ import annotations

from typing import Optional

from livekit.agents import llm as lk_llm
from livekit.plugins import openai as lk_openai

from llm_stream import LLMConfig, reasoning_kwargs, targets


def build_llm(config: Optional[LLMConfig] = None, **kwargs) -> lk_llm.LLM:
    """Return a livekit-agents LLM plugin pointed at LLM_BASE_URL/LLM_MODEL.

    Works with any OpenAI-compatible chat completions endpoint (Groq,
    Cerebras, etc.) since livekit's openai.LLM plugin accepts an arbitrary
    base_url.
    """
    config = config or LLMConfig.from_env()
    chain = [lk_openai.LLM(model=m, api_key=key, base_url=config.base_url, **kwargs, **reasoning_kwargs(m))
             for m, key, _ in targets(config)]
    # free tiers cap tokens per model per day: on a 429 the call moves to the next model (or key) instead of failing
    return chain[0] if len(chain) == 1 else lk_llm.FallbackAdapter(chain, attempt_timeout=8.0)
