"""Chat-bubble and CEO tool-call SSE event factories."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agentcore.core.log_context import get_log_value
from agentcore.runtime.events.types import EventType, FinishReason, SSEEvent

if TYPE_CHECKING:
    from agentcore.runtime.events.payloads.chat import ResetReason

_DISPLAY_STR_CAP = 6000
_DISPLAY_LIST_CAP = 50


def message_start(
    message_id: str, *, conversation_id: str, trace_id: str | None = None
) -> SSEEvent:
    payload: dict[str, Any] = {
        "message_id": message_id,
        "conversation_id": conversation_id,
    }
    tid = trace_id if trace_id is not None else get_log_value("trace_id")
    if tid:
        payload["trace_id"] = tid
    return SSEEvent(type=EventType.MESSAGE_START, payload=payload)


def turn_warning(message: str) -> SSEEvent:
    """Preflight soft gate — model may not support tool calling (BYOK probe hint)."""
    return SSEEvent(type=EventType.TURN_WARNING, payload={"message": message})


def content_delta(delta: str) -> SSEEvent:
    return SSEEvent(type=EventType.CONTENT_DELTA, payload={"delta": delta})


def content_reset(reason: ResetReason) -> SSEEvent:
    """清空 CEO 气泡已流式正文。``reason`` 必填（见 payloads.chat.ResetReason）：客户端仅对
    ``finish_guard`` 折出「已按交付规范重写」痕迹，其余 reason 只清正文、不留 chip。"""
    return SSEEvent(type=EventType.CONTENT_RESET, payload={"reason": reason})


def reasoning_delta(delta: str) -> SSEEvent:
    return SSEEvent(type=EventType.REASONING_DELTA, payload={"delta": delta})


def tool_progress(tool_name: str, chars: int) -> SSEEvent:
    return SSEEvent(
        type=EventType.TOOL_PROGRESS,
        payload={"tool_name": tool_name, "chars": chars},
    )


def tool_use_progress(
    tool_call_id: str,
    tool_name: str,
    phase: str,
    *,
    run_id: str = "",
    extra: dict[str, Any] | None = None,
) -> SSEEvent:
    """A running tool reported a coarse EXECUTION phase (工具执行阶段进度).

    Emitted between ``tool_use_start`` and ``tool_use_end`` so the waiting UI shows a
    live, honest state instead of a bare spinner. ``phase`` is a short machine token the
    client maps to text (``web_search`` → ``querying`` 正在检索 / ``queued`` 排队中 /
    ``fallback`` 改用备用引擎). Transport-only liveliness: never journaled, never folded
    into the process timeline — a reloaded turn's tools are already resolved. Carries
    ``run_id`` for a delegated worker's call (like the tool_use_start/end pair)."""
    payload: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "phase": phase,
    }
    if run_id:
        payload["run_id"] = run_id
    if extra:
        payload.update(extra)
    return SSEEvent(type=EventType.TOOL_USE_PROGRESS, payload=payload)


def tool_use_start(
    tool_call_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    run_id: str = "",
) -> SSEEvent:
    payload: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "arguments": arguments,
    }
    if run_id:
        payload["run_id"] = run_id
    return SSEEvent(type=EventType.TOOL_USE_START, payload=payload)


def citations_event(citations: list[dict[str, Any]]) -> SSEEvent:
    return SSEEvent(type=EventType.CITATIONS, payload={"citations": citations})


def evidence_ledger_event(
    *,
    delta: list[dict[str, Any]] | None = None,
    entries: list[dict[str, Any]] | None = None,
    cited_ids: list[str] | None = None,
) -> SSEEvent:
    """Turn 级台账通道（引用即出处）——独立于 ``citations_event``（P2 主卡=引用集）。"""
    payload: dict[str, Any] = {"delta": list(delta or [])}
    if entries is not None:
        payload["entries"] = list(entries)
    if cited_ids is not None:
        payload["cited_ids"] = list(cited_ids)
    return SSEEvent(type=EventType.EVIDENCE_LEDGER, payload=payload)


def _cap_display_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_DISPLAY_STR_CAP] + "…" if len(value) > _DISPLAY_STR_CAP else value
    if isinstance(value, list):
        return [_cap_display_value(v) for v in value[:_DISPLAY_LIST_CAP]]
    if isinstance(value, dict):
        return {k: _cap_display_value(v) for k, v in value.items()}
    return value


def _cap_display(display: dict[str, Any] | None) -> dict[str, Any] | None:
    if not display:
        return None
    return {k: _cap_display_value(v) for k, v in display.items()}


def tool_use_end(
    tool_call_id: str,
    tool_name: str,
    *,
    success: bool,
    output: str,
    display: dict[str, Any] | None = None,
    run_id: str = "",
) -> SSEEvent:
    payload: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "status": "success" if success else "error",
        "result": output,
    }
    capped = _cap_display(display)
    if capped is not None:
        payload["display"] = capped
    if run_id:
        payload["run_id"] = run_id
    return SSEEvent(type=EventType.TOOL_USE_END, payload=payload)


def _wire_cost(cost: dict[str, Any] | None) -> dict[str, Any] | None:
    if cost is None:
        return None
    out: dict[str, Any] = {
        "input": int(cost.get("input", 0) or 0),
        "cached": int(cost.get("cached", 0) or 0),
        "output": int(cost.get("output", 0) or 0),
        "total": int(cost.get("total", 0) or 0),
        "currency": str(cost.get("currency") or "CNY"),
        "pricing_source": str(cost.get("pricing_source") or "curated"),
    }
    if cost.get("estimated_total") is not None:
        out["estimated_total"] = int(cost["estimated_total"])
    return out


def message_end(
    finish_reason: FinishReason,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    rounds: int = 0,
    cost: dict[str, Any] | None = None,
    collab: dict[str, int] | None = None,
) -> SSEEvent:
    payload: dict[str, Any] = {
        "finish_reason": finish_reason,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "cache_hit_tokens": cache_hit_tokens,
            "cache_miss_tokens": cache_miss_tokens,
        },
        "cost": _wire_cost(cost),
        "rounds": rounds,
    }
    if collab is not None:
        payload["collab"] = collab
    return SSEEvent(type=EventType.MESSAGE_END, payload=payload)


def error_event(code: str, message: str, *, context: dict | None = None) -> SSEEvent:
    payload: dict = {"code": code, "message": message}
    if context:
        payload["context"] = context
    return SSEEvent(
        type=EventType.ERROR,
        payload=payload,
    )


def title_generated(title: str, *, conversation_id: str) -> SSEEvent:
    payload: dict[str, str] = {"conversation_id": conversation_id, "title": title}
    return SSEEvent(
        type=EventType.TITLE_GENERATED,
        payload=payload,
    )


def followups_generated(
    followups: list[str], *, conversation_id: str, message_id: str
) -> SSEEvent:
    """CEO→用户「下一步推荐」(下一步推荐): quick-reply chips for the just-finished turn.

    Attached client-side to the assistant row identified by ``message_id`` (same id as
    ``set_followups``). Emitted only when there is at least one suggestion (a no-op
    event carries no UX), after ``message_end``. Missing ``message_id`` is a caller bug —
    clients no-op rather than falling back to「last assistant」.
    """
    return SSEEvent(
        type=EventType.FOLLOWUPS_GENERATED,
        payload={
            "conversation_id": conversation_id,
            "message_id": message_id,
            "followups": followups,
        },
    )


def followups_unavailable(
    *, conversation_id: str, message_id: str, reason: str
) -> SSEEvent:
    """Soft hint that followups mint failed — not a turn-blocking error."""
    return SSEEvent(
        type=EventType.FOLLOWUPS_UNAVAILABLE,
        payload={
            "conversation_id": conversation_id,
            "message_id": message_id,
            "reason": reason,
        },
    )


def turn_saved(*, user_message_id: str) -> SSEEvent:
    return SSEEvent(
        type=EventType.TURN_SAVED,
        payload={"user_message_id": user_message_id},
    )
