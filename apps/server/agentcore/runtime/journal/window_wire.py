"""Project a turn journal into the diagnostic LLM-window wire shape."""

from __future__ import annotations

from typing import Any

from agentcore.api.schemas.llm_window import (
    LlmWindowMessageLine,
    LlmWindowToolCall,
    LlmWindowToolCallFunction,
    RunLlmWindowResponse,
)
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.facts import FactKind
from agentcore.runtime.journal import window_from_journal


def _history_len(entries: list[dict[str, Any]]) -> int:
    for entry in entries:
        if (entry.get("kind") or "") == FactKind.TURN_STARTED.value:
            return int((entry.get("payload") or {}).get("history_len") or 0)
    return 0


def _run_head_user_origin(entries: list[dict[str, Any]], run_id: str) -> str | None:
    """Return ``user_origin`` from this run's ``run_head`` fact, if any."""
    for entry in entries:
        if (entry.get("kind") or "") != FactKind.RUN_HEAD.value:
            continue
        payload = entry.get("payload") or {}
        if payload.get("run_id") == run_id:
            origin = payload.get("user_origin") or ""
            return str(origin) if origin else None
    return None


def _llm_message_to_wire(
    msg: LLMMessage,
    *,
    origin: str | None = None,
) -> LlmWindowMessageLine:
    tool_calls = None
    if msg.tool_calls:
        tool_calls = [
            LlmWindowToolCall(
                id=tc.id,
                type=tc.type,
                function=LlmWindowToolCallFunction(
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ),
            )
            for tc in msg.tool_calls
        ]
    return LlmWindowMessageLine(
        role=msg.role,
        content=msg.content,
        tool_calls=tool_calls,
        tool_call_id=msg.tool_call_id,
        reasoning_content=msg.reasoning_content,
        origin=origin,
    )


def project_run_llm_window(
    entries: list[dict[str, Any]] | None,
    *,
    run_id: str,
    history: list[dict] | None = None,
) -> RunLlmWindowResponse:
    """Fold journal facts into one run's LLM input window for diagnostic replay."""
    if not entries:
        return RunLlmWindowResponse(run_id=run_id, available=False, messages=[])

    history_msgs = (
        [LLMMessage(role=h["role"], content=h["content"]) for h in history] if history else None
    )
    window = window_from_journal(entries, run_id=run_id, history=history_msgs)
    if not window:
        return RunLlmWindowResponse(run_id=run_id, available=False, messages=[])

    # Opening user composed from ContextBlocks → tag for the diagnostic UI merge.
    head_origin = _run_head_user_origin(entries, run_id)
    messages: list[LlmWindowMessageLine] = []
    saw_opening_user = False
    for msg in window:
        origin: str | None = None
        if (
            head_origin
            and not saw_opening_user
            and msg.role == "user"
            and not msg.tool_call_id
        ):
            origin = head_origin
            saw_opening_user = True
        messages.append(_llm_message_to_wire(msg, origin=origin))

    return RunLlmWindowResponse(
        run_id=run_id,
        available=True,
        messages=messages,
    )


def history_len_from_journal(entries: list[dict[str, Any]] | None) -> int:
    """Expose ``turn_started.history_len`` for the route's history loader."""
    if not entries:
        return 0
    return _history_len(entries)
