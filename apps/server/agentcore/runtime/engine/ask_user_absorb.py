"""Content absorption for blocking ``ask_user``.

When the model streams prose and calls blocking ``ask_user`` in the same round, the
engine folds that prose into the card (or discards it when ``message`` is explicit)
instead of leaving duplicate text in the bubble / transcript.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from agentcore.core.types import ToolEffect
from agentcore.llm.provider.protocol import LLMMessage, ToolCall
from agentcore.runtime.facts import FactKind, current_fact_log
from agentcore.runtime.loop_controller import ToolAttempt

from .segments import tool_calls_to_dicts


def _parse_args(tc: ToolCall) -> dict[str, Any]:
    try:
        return json.loads(tc.function.arguments) if tc.function.arguments else {}
    except json.JSONDecodeError:
        return {}


def is_blocking_ask_user(tc: ToolCall) -> bool:
    if tc.function.name != "ask_user":
        return False
    args = _parse_args(tc)
    blocking_arg = args.get("blocking")
    return True if blocking_arg is None else bool(blocking_arg)


def _patch_tool_call_args(tc: ToolCall, args: dict[str, Any]) -> ToolCall:
    return replace(
        tc,
        function=replace(
            tc.function,
            arguments=json.dumps(args, ensure_ascii=False),
        ),
    )


def prepare_blocking_ask_user_tool_calls(
    tool_calls: list[ToolCall],
    round_content: str,
) -> list[ToolCall]:
    """Inject ``round_content`` into a blocking ``ask_user`` when ``message`` is empty."""
    content = (round_content or "").strip()
    if not content:
        return tool_calls
    patched: list[ToolCall] = []
    for tc in tool_calls:
        if not is_blocking_ask_user(tc):
            patched.append(tc)
            continue
        args = _parse_args(tc)
        if str(args.get("message") or "").strip():
            patched.append(tc)
            continue
        args["message"] = content
        patched.append(_patch_tool_call_args(tc, args))
    return patched


def _blocking_ask_user_succeeded(
    tool_calls: list[ToolCall],
    attempts: list[ToolAttempt],
) -> bool:
    for tc, attempt in zip(tool_calls, attempts, strict=False):
        if is_blocking_ask_user(tc) and attempt.success:
            return True
    return False


def _amend_last_llm_call(
    *,
    content: str,
    tool_calls: list[ToolCall] | None = None,
) -> None:
    log = current_fact_log.get()
    if log is None:
        return
    facts = log._facts  # noqa: SLF001 - paired write-back for the in-memory journal
    for i in range(len(facts) - 1, -1, -1):
        if facts[i].kind != FactKind.LLM_CALL.value:
            continue
        payload = dict(facts[i].payload)
        payload["content"] = content
        if tool_calls is not None:
            payload["tool_calls"] = tool_calls_to_dicts(tool_calls)
        from agentcore.runtime.facts import Fact

        facts[i] = Fact(kind=facts[i].kind, payload=payload, ts=facts[i].ts)
        return


def absorb_blocking_ask_user_content(
    *,
    messages: list[LLMMessage],
    tool_calls: list[ToolCall],
    attempts: list[ToolAttempt],
    terminal_effect: ToolEffect | None,
    emit_reset: Any,
) -> bool:
    """Clear absorbed assistant prose after a successful blocking ``ask_user`` pause.

    Returns ``True`` when content was absorbed (caller should roll back ``final_content``).
    """
    if terminal_effect is not ToolEffect.SUSPEND:
        return False
    if not _blocking_ask_user_succeeded(tool_calls, attempts):
        return False
    if not messages or messages[-1].role != "assistant":
        return False

    messages[-1] = replace(messages[-1], content=None)
    _amend_last_llm_call(content="", tool_calls=tool_calls)
    emit_reset("ask_user")
    return True
