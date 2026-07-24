"""Split from executor.py — see executor.py module docstring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.llm.pricing import calculate_cost
from agentcore.llm.profiles import ProfileParams
from agentcore.llm.provider.protocol import LLMMessage, LLMProvider, TokenUsage
from agentcore.runtime.approvals import ApprovalGate
from agentcore.runtime.engine import react_loop
from agentcore.runtime.events import (
    EventSink,
    FinishReason,
    run_output_delta,
    run_output_reset,
    run_reasoning_delta,
    run_tool_progress,
)
from agentcore.runtime.runs.contract import synthesize_debrief
from agentcore.runtime.runs.cutoff import warning_for_reason
from agentcore.runtime.runs.types import Deliverable, RunPhase, RunState
from agentcore.tools.protocol import Tool, ToolContext
from agentcore.tools.registry import ToolRegistry

logger = get_logger(__name__)

# LLM 流在收尾轮被掐断（post-commit disconnect / hard LLM failure → Return ERROR|DEGRADED）
# 时写入 RunState.warnings，供 CEO collect_worker_gaps 暴露。
_FINISH_INTERRUPT_REASONS = frozenset({FinishReason.ERROR, FinishReason.DEGRADED})
FINISH_INTERRUPT_WARNING = (
    "LLM 流在收尾时中断：产物可能已落盘，但交接简报缺失或不完整"
)


def _delivery_gaps_from_warnings(
    warnings: list[str],
    debrief: dict[str, Any] | None,
) -> list[dict[str, str]]:
    """Build first-class delivery_gaps rows from soft-accept warnings + debrief."""
    from agentcore.runtime.runs.cutoff import (
        DEGRADED_HANDOFF_WARNING,
        REASON_DEGRADED_HANDOFF,
        reason_for_warning,
    )

    gaps: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in warnings or []:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        row: dict[str, str] = {"description": text}
        code = reason_for_warning(text)
        if code:
            row["reason"] = code
        gaps.append(row)
    if isinstance(debrief, dict) and debrief.get("degraded"):
        text = DEGRADED_HANDOFF_WARNING
        if text not in seen:
            gaps.append({"description": text, "reason": REASON_DEGRADED_HANDOFF})
    return gaps


def _hard_gap_blocks_completion(
    delivery_gaps: list[dict[str, str]],
    debrief: dict[str, Any] | None,
    deliverable: Deliverable | None,
) -> str | None:
    """Wave3 C: strict nodes must not COMPLETE with hard gaps / degraded_handoff.

    Soft anti-slop warnings alone do not trip this. Missing-artifact soft-accept is
    already blocked by ``strict=True`` via :func:`_is_hard_failure`. Returns a fail
    reason (CEO may ``continue_from_run_id``) or ``None`` to allow COMPLETED.
    """
    if deliverable is None or not deliverable.strict:
        return None
    from agentcore.runtime.runs.cutoff import (
        DEGRADED_HANDOFF_WARNING,
        REASON_DEGRADED_HANDOFF,
    )

    for gap in delivery_gaps or []:
        if not isinstance(gap, dict):
            continue
        reason = str(gap.get("reason") or "").strip()
        desc = str(gap.get("description") or "").strip()
        if reason == REASON_DEGRADED_HANDOFF or DEGRADED_HANDOFF_WARNING in desc:
            return (
                "硬缺口：降级交接（degraded_handoff），不得冒充完成；"
                "请 continue_from_run_id 续派或冷补派"
            )
        if "未落盘" in desc or "未在工作区找到" in desc:
            return (
                "硬缺口：声明交付物未落盘，不得冒充完成；"
                "请 continue_from_run_id 续派或冷补派"
            )
    if isinstance(debrief, dict) and debrief.get("degraded"):
        return (
            "硬缺口：降级交接（degraded_handoff），不得冒充完成；"
            "请 continue_from_run_id 续派或冷补派"
        )
    return None


def _apply_cutoff_reasons(
    cutoff_reasons: list[str],
    *,
    warnings: list[str],
) -> list[str]:
    """Merge structured cutoff reason codes into RunState.warnings (idempotent)."""
    out = list(warnings)
    for reason in cutoff_reasons:
        text = warning_for_reason(reason)
        if text and text not in out:
            out.append(text)
    return out


def _registry_with(base: ToolRegistry, *extra: Tool) -> ToolRegistry:
    """A per-worker registry = the shared team tools + the worker's own extra tools
    (its nested ``delegate`` and the companion ``replan`` that supervises that
    delegate's sub-plan). Returns a fresh registry; the shared ``base`` is never
    mutated (it backs every worker in the team and must stay delegate-free for leaf
    workers)."""
    registry = ToolRegistry()
    for schema in base.list_all():
        registry.register(base.get(schema.name))
    for tool in extra:
        registry.register(tool)
    return registry


def _registry_without(base: ToolRegistry, *names: str) -> ToolRegistry:
    """A per-worker registry = the team tools MINUS ``names`` (absent names ignored).

    The inverse of :func:`_registry_with`: a NON-collaborative batch (``collaboration=
    False`` — an adversarial / independent fan-out such as a debate, where 正方 vs 反方
    are opponents rather than teammates) strips the 团队便签 tools (post/read/amend_note)
    so even an UNRESTRICTED worker ("offer all team tools") is never handed a
    collaboration channel. Returns a fresh registry; the shared ``base`` is never
    mutated."""
    drop = set(names)
    registry = ToolRegistry()
    for schema in base.list_all():
        if schema.name not in drop:
            registry.register(base.get(schema.name))
    return registry


def _priced_failure(
    error: str,
    *,
    model: str | None,
    usage: TokenUsage,
    rounds: int,
    duration_ms: int,
    retryable: bool = True,
) -> RunState:
    """A FAILED RunState that still carries the tokens the run spent before it died.

    B-deep 失败计费: a hard exception used to drop a run's already-consumed usage —
    it lived only inside the ``try`` — so a worker that failed on round 4 under-billed
    rounds 1–3 (real spend on DeepSeek's side, invisible in the ledger). The
    accumulated ``usage`` is priced here exactly once (via ``calculate_cost``) so a
    failed-but-metered run produces a ledger row like any other run. ``usage``/``cost``
    are left empty when nothing was spent (run failed before any LLM call, or before
    the model tier resolved), so the per-run accumulator's ``if state.usage`` guard
    still skips a never-metered failure — no spurious zero rows.

    ``retryable`` (确定性失败区分, BL-6) rides onto the state so the WaveScheduler can
    skip its infra retry for a deterministic upstream failure (prompt 超长 / 鉴权 / 余额)
    that would just re-fail identically. Defaults True (transient / unknown crash → retry
    as before).
    """
    has_usage = bool(usage.input_tokens or usage.output_tokens)
    return RunState(
        phase=RunPhase.FAILED,
        error=error,
        error_retryable=retryable,
        model=model or "",
        duration_ms=duration_ms,
        rounds=rounds,
        usage=usage.as_dict() if has_usage else {},
        cost=asdict(calculate_cost(model, usage)) if (model and has_usage) else {},
    )


def _is_hard_failure(content: str, deliverable: Deliverable | None) -> bool:
    """Whether a contract miss should FAIL the run vs. soft-accept with a warning.

    An empty product is always hard (the non-empty baseline, 决策②); any other
    shortfall is hard only when the deliverable is ``strict`` (默认软提醒, 决策③)."""
    if not content.strip():
        return True
    return deliverable is not None and deliverable.strict


def _apply_finish_interrupt(
    finish_override: list[FinishReason],
    *,
    warnings: list[str],
    debrief: dict[str, Any] | None,
    content: str,
    files_touched: list[str],
    run_id: str = "",
) -> tuple[list[str], dict[str, Any] | None]:
    """Annotate COMPLETED workers whose accepted react pass ended ERROR/DEGRADED.

    Clean ``Return()`` leaves ``finish_override`` empty — no warning. Other
    FinishReasons (UNPRODUCTIVE / PAUSED / …) are out of scope here.
    """
    if not finish_override:
        return warnings, debrief
    fr = finish_override[-1]
    if fr not in _FINISH_INTERRUPT_REASONS:
        return warnings, debrief
    out_warnings = list(warnings)
    if FINISH_INTERRUPT_WARNING not in out_warnings:
        out_warnings.append(FINISH_INTERRUPT_WARNING)
    out_debrief = debrief
    synthesized = False
    if out_debrief is None:
        out_debrief = synthesize_debrief(content, files_touched)
        synthesized = True
    logger.warning(
        "run.finish_interrupted",
        run_id=run_id,
        finish_reason=fr.value,
        debrief_synthesized=synthesized,
    )
    return out_warnings, out_debrief


async def _react_and_capture(
    messages: list[LLMMessage],
    *,
    llm: LLMProvider,
    tools: ToolRegistry,
    sink: EventSink,
    tool_ctx: ToolContext,
    profile: ProfileParams,
    turn_model: str,
    allowed_tools: list[str] | None,
    run_id: str,
    agent_id: str,
    citation_sink: list[dict],
    approval_gate: ApprovalGate | None,
    usage_sink: list[TokenUsage] | None = None,
    on_round_begin: Callable[[], list[LLMMessage]] | None = None,
    round_sink: list[int] | None = None,
    streamed_content: list[str] | None = None,
    gate_escalation_sink: list[dict] | None = None,
    token_budget: int = 0,
    finish_override_sink: list[FinishReason] | None = None,
    cutoff_reason_sink: list[str] | None = None,
    tool_failure_sink: list[dict] | None = None,
    turn_evidence_ledger: object | None = None,
    ledger_registrant: str = "",
) -> tuple[str, str, TokenUsage, int]:
    """Run one ReAct pass over ``messages`` (mutated in place — the loop appends
    each assistant tool-call turn + tool results), then append the final assistant
    answer so the transcript ends with the worker's product.

    This is the shared core of both the initial worker run and a 续写 (auto-rework /
    revise): ``react_loop`` returns the final no-tool answer WITHOUT appending it
    (engine returns before the append), so we add it here — making ``messages`` a
    complete, replayable transcript for capture and continuation.

    Returns the loop's full ``reasoning`` alongside ``content`` so the caller can
    carry it onto the worker's terminal :class:`RunState` → its ``message_final``
    fact (执行级事件溯源: deltas 退场). The worker's thinking is the run's authoritative
    fact there; ``run_reasoning_delta`` stays as a transport-only live signal (no
    longer journaled), exactly like ``run_output_delta`` / ``run_tool_progress``.

    ``usage_sink`` is forwarded to the loop so that when this pass raises (workers
    run with ``raise_on_error=True``), the caller can still read the tokens spent on
    the rounds that completed before the failure (B-deep 失败计费).

    ``streamed_content`` (run_redirect 热续写): when given, each ``run_output_delta``
    chunk is also appended here so a mid-flight cancel can salvage the draft the
    user already saw even before the final assistant turn is appended to ``messages``.

    ``finish_override_sink`` mirrors the captain path: when the loop ends on a
    non-default terminal (ERROR / DEGRADED from an aborted LLM stream, …) the
    reason is appended so the worker executor can surface a soft warning instead of
    silently treating the run as a clean COMPLETED.

    ``cutoff_reason_sink`` collects structured pinch codes (e.g. ``token_budget``)
    for delivery_status / CEO gap transparency — orthogonal to DEGRADED thrashing.

    ``tool_failure_sink`` receives this pass's tool-failure fact dicts (circuit-breaker
    tally) for ``RunState.tool_failures`` → CEO ``tool_failures`` section.
    """
    def _on_content(delta: str) -> None:
        sink.emit(run_output_delta(run_id, agent_id, delta))
        if streamed_content is not None:
            streamed_content.append(delta)

    content, reasoning, usage, rounds = await react_loop(
        messages=messages,
        llm=llm,
        tools=tools,
        sink=sink,
        tool_context=tool_ctx,
        profile=profile,
        turn_model=turn_model,
        allowed_tool_names=allowed_tools,
        on_content=_on_content,
        on_reasoning=lambda d: sink.emit(run_reasoning_delta(run_id, agent_id, d)),
        on_tool_progress=lambda tool, chars: sink.emit(
            run_tool_progress(run_id, agent_id, tool, chars)
        ),
        on_reset=lambda reason: sink.emit(run_output_reset(run_id, agent_id, reason)),
        raise_on_error=True,
        citation_sink=citation_sink,
        # [n] 造引用查仍关；#rN id 存在闸由 turn_evidence_ledger + 正文标记启用（Q5）。
        annotate_citations=False,
        turn_evidence_ledger=turn_evidence_ledger,  # type: ignore[arg-type]
        ledger_registrant=ledger_registrant,
        approval_gate=approval_gate,
        usage_sink=usage_sink,
        on_round_begin=on_round_begin,
        round_sink=round_sink,
        run_id=run_id,
        role="worker",
        # 交付正文只留最终交付、旁白入 journal (Fork-B, 全队对称): a worker/debater/revision's
        # persisted product (message_final → run card 重载合成 + CEO synthesis input +
        # contract/debrief harvest) drops the prose it streams before a non-terminal tool
        # (a lead-in / steer acknowledgement). Because a worker's live card shares the
        # deliverable channel, react_loop also emits run_output_reset (via on_reset above)
        # so 直播==重载 — keeping the conformance invariant while cleaning the product.
        deliverable_only=True,
        gate_escalation_sink=gate_escalation_sink,
        token_budget=token_budget,
        finish_override_sink=finish_override_sink,
        cutoff_reason_sink=cutoff_reason_sink,
        tool_failure_sink=tool_failure_sink,
    )
    messages.append(LLMMessage(role="assistant", content=content))
    return content, reasoning, usage, rounds


def _retry_message(feedback: str) -> LLMMessage:
    """The auto-rework turn appended to a worker's transcript when its product
    misses the contract. The worker now sees its own prior draft above this, so the
    feedback ("补齐差距、其余保持原样") is finally coherent (修隐患)."""
    return LLMMessage(role="user", content=feedback)


def _continuation_message(feedback: str) -> LLMMessage:
    """统一「续干」指令：追加到 worker 已保存 transcript，同一作者带现场接着干。

    改稿 / 接新任务 / redirect 热修 / 辩论续轮共用此模板；区别只在 ``feedback`` 内容
    （及调用方注入的依赖产物块）。"""
    return LLMMessage(
        role="user",
        content=(
            f"## 续干指令\n{feedback}\n\n"
            "请在你已有现场与上一版产出的基础上继续完成上述指令，"
            "直接输出【完整最终产出】；未提及之处保持原样，"
            "不要解释、不要复述改动清单。"
        ),
    )
