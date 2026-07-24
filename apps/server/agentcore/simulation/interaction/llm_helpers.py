"""Lightweight LLM helpers for interaction protocols."""

from __future__ import annotations

import json
import re

from agentcore.llm.provider.protocol import LLMMessage, LLMProvider, LLMRequest


async def sim_complete_text(
    llm: LLMProvider,
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.7,
) -> str:
    response = await llm.complete(
        LLMRequest(
            messages=[
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user),
            ],
            model=model,
            temperature=temperature,
            stream=False,
            scenario="sim.interaction",
        )
    )
    return (response.content or "").strip()


def parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
    return None


async def sim_complete_json(
    llm: LLMProvider,
    *,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.7,
) -> tuple[dict | None, str]:
    raw = await sim_complete_text(
        llm,
        model=model,
        system=system,
        user=user,
        temperature=temperature,
    )
    return parse_json_object(raw), raw
