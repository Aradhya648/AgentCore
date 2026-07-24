"""Chat-bubble SSE payload wire models (factories: ``runtime/events/chat.py``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field

from agentcore.runtime.events.payloads._base import WirePayload, absent
from agentcore.runtime.events.payloads.shared import CostBreakdown
from agentcore.runtime.events.types import FinishReason


class MessageStartPayload(WirePayload):
    message_id: str
    conversation_id: str
    trace_id: str | None = absent(
        "The turn's log correlation id (32-hex), for one-step log lookup. Omitted when the "
        "turn ran without a trace context (e.g. conformance vectors built outside a turn)."
    )


class ContentDeltaPayload(WirePayload):
    delta: str


# 为什么发这次 reset——客户端按它决定「清正文之外还留不留痕迹」：
# - finish_guard：交付前核验回炉，唯一折出「已按交付规范重写」chip（didRework）的 reason；
# - retry：LLM 流式传输透明重试，丢弃上次尝试的临时输出（基础设施噪音，不留痕）；
# - soft_gate：captain 收尾草稿被软门控（组队/审计）打回重来（后续组队/审计动作自带痕迹）；
# - narration：worker 调非终止工具前的旁白回滚（正常流程，旁白只进 journal）；
# - ask_user：blocking ask_user 暂停时同轮正文被吸收进提问卡片。
ResetReason = Literal["finish_guard", "retry", "soft_gate", "narration", "ask_user"]


class ContentResetPayload(WirePayload):
    """清空当前流式气泡已累积正文的信号——客户端清正文后再接收重写版 `content_delta`。
    ``reason`` 表明本次 reset 的语义（见 `ResetReason`）；仅 ``finish_guard``（交付前核验
    回炉）折出「已按交付规范重写」痕迹，其余 reason 只清正文、不留 chip。Transport-only。"""

    reason: ResetReason = Field(json_schema_extra={"ts_type": "ResetReason"})


class ReasoningDeltaPayload(WirePayload):
    delta: str


class ToolProgressPayload(WirePayload):
    """The CEO captain is composing a tool call's ARGUMENTS (bubble-scoped twin of
    `RunToolProgressPayload`). Transport-only liveliness: never journaled."""

    tool_name: str
    chars: int


# A running tool's coarse EXECUTION phase (工具执行阶段进度). Known values:
# web_search → queued / querying / fallback; read_url → fetching / reading / blocked;
# code_execute → executing. Kept as a widened `string` on the wire so the backend can add
# phases without a client bump — an unknown value maps to a generic「处理中」.
ToolPhase = Literal[
    "queued",
    "querying",
    "fallback",
    "fetching",
    "reading",
    "executing",
    "blocked",
]


class ToolUseProgressPayload(WirePayload):
    """A running tool reported an EXECUTION phase — emitted between `tool_use_start` and
    `tool_use_end` so the waiting UI shows a live, honest state instead of a bare spinner.
    Transport-only: NEVER journaled and NEVER folded into the process timeline. May carry
    extra tool-specific keys (e.g. code_execute output streaming `stream`/`chunk`)."""

    # Tools may ride extra progress data on this transport-only event (`extra=` merge in
    # the factory), so unknown keys are NOT drift here.
    model_config = ConfigDict(extra="allow")

    tool_call_id: str
    tool_name: str
    phase: str
    run_id: str | None = absent("Present for a delegated worker's call.")


class ToolUseStartPayload(WirePayload):
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    run_id: str | None = absent(
        "Present (run id) when a DELEGATED WORKER raised this call — process folds skip a "
        "tagged call (it belongs to that worker's run node, not the CEO's timeline). "
        "Absent for the captain's own calls."
    )


class ToolUseEndPayload(WirePayload):
    tool_call_id: str
    tool_name: str
    result: str
    status: Literal["success", "error"]
    display: dict[str, Any] | None = Field(
        default=None,
        description=(
            "A tool's OPTIONAL render-oriented payload (工具结果富渲染), distinct from the "
            "model-facing `result` text."
        ),
        json_schema_extra={"ts_type": "ToolDisplay"},
    )
    run_id: str | None = absent("Worker-call tag; absent for the captain's own calls.")


class TitleGeneratedPayload(WirePayload):
    conversation_id: str
    title: str


class FollowupsGeneratedPayload(WirePayload):
    """CEO→用户「下一步推荐」: 2-4 quick-reply chips for the just-finished turn, emitted
    after `message_end`. Persisted on `Message.followups` (DERIVED), no-op in folds.
    `message_id` is the assistant row the chips belong to (same id as `set_followups`)."""

    conversation_id: str
    message_id: str
    followups: list[str]


class TurnSavedPayload(WirePayload):
    user_message_id: str


class TurnWarningPayload(WirePayload):
    """BYOK soft gate: preflight hint when probe says the user's model may lack tool
    calling. Transport-only — not journaled."""

    message: str


class ErrorContext(WirePayload):
    upstream_status: int | None = absent()
    upstream_body_preview: str | None = None
    retry_attempts: int | None = absent()
    empty_diagnosis: str | None = absent()


class ErrorPayload(WirePayload):
    code: str
    message: str
    context: ErrorContext | None = absent()


class MessageEndUsage(WirePayload):
    """Turn token totals (long-key form, contrast `UsageBreakdown` short keys on runs)."""

    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int


class TurnCollabMetrics(WirePayload):
    """协作质量: turn-level orchestration signals for 诊断模式. Omitted on single-agent
    turns and legacy streams."""

    boundary_yields: int
    scope_signals: int
    revises: int
    escalations: int
    audit_drops: int | None = absent("审计采集降级计数 (turn_metrics.audit_drops); 诊断模式 only.")


class MessageEndPayload(WirePayload):
    """Terminal turn event. `finish_reason=paused` = 挂起即收口: the turn finalized AT a
    durable checkpoint and awaits POST .../resume — NOT done and not aborted."""

    finish_reason: FinishReason
    usage: MessageEndUsage | None = absent()
    cost: CostBreakdown | None = absent()
    rounds: int | None = absent()
    collab: TurnCollabMetrics | None = absent()
