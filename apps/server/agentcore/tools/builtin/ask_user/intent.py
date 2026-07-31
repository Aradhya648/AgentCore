"""Resolve ask_user checkpoint intent at emission time.

Scene kickoff / 开工提案 product surface removed: ordinary asks are ``decision``.
Explicit ``card`` still overrides via :func:`card_overrides_intent`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentcore.runtime.checkpoints import AskCheckpointIntent

if TYPE_CHECKING:
    from agentcore.llm.provider.protocol import LLMMessage

# Tools that mean the CEO has moved into execution — subsequent ask_user is mid-task.
_EXECUTION_TOOLS = frozenset(
    {
        "delegate",
        "debate",
        "replan",
        "file_write",
        "file_append",
        "str_replace",
        "code_execute",
        "test_run",
    }
)

# Skills that teach ask_user shapes — all resolve to ordinary decision (no kickoff shell).
_SKILL_INTENT: dict[str, AskCheckpointIntent] = {
    "ask_user_kickoff": "decision",
    "ask_user_midtask": "decision",
}


def _prior_tool_names(transcript: list[LLMMessage]) -> list[str]:
    """Tool names from assistant turns before the trailing ``ask_user`` suspend."""
    last_ask_idx: int | None = None
    for i, msg in enumerate(transcript):
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        if any(tc.function.name == "ask_user" for tc in msg.tool_calls):
            last_ask_idx = i

    end = last_ask_idx if last_ask_idx is not None else len(transcript)
    names: list[str] = []
    for msg in transcript[:end]:
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            names.append(tc.function.name)
    return names


def _last_consulted_skill(transcript: list[LLMMessage]) -> str | None:
    skill: str | None = None
    for msg in transcript:
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            if tc.function.name != "consult_skill":
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                continue
            name = str(args.get("name") or "").strip()
            if name:
                skill = name
    return skill


def resolve_ask_checkpoint_intent(
    transcript: list[LLMMessage] | None,
) -> AskCheckpointIntent:
    """Classify a blocking ``ask_user`` pause for the ``checkpoint_required`` payload.

    Ordinary clarifying asks are always ``decision`` (kickoff / 开工提案 shell removed).
    Derived from the live CEO transcript at suspend time — never inferred downstream.
    """
    if not transcript:
        return "decision"

    prior = _prior_tool_names(transcript)
    if "ask_user" in prior or any(name in _EXECUTION_TOOLS for name in prior):
        return "decision"

    skill = _last_consulted_skill(transcript)
    if skill in _SKILL_INTENT:
        return _SKILL_INTENT[skill]

    return "decision"
