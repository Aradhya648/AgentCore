"""Single ReAct round: request projection, LLM streaming, facts, no-tool finish paths."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agentcore.config import settings
from agentcore.core.error_codes import ErrorCode
from agentcore.core.errors import LLMUpstreamError, error_fields_for
from agentcore.core.logging import get_logger
from agentcore.llm.profiles import ProfileParams, build_request
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.llm.provider.protocol import LLMMessage, TokenUsage
from agentcore.llm.tools_gate import TOOLS_UNAVAILABLE_RUNTIME_MESSAGE
from agentcore.runtime.citations import (
    invalid_ledger_ref_ids,
    strip_invalid_ledger_refs,
)
from agentcore.runtime.events import FinishReason
from agentcore.runtime.evidence_ledger import EvidenceLedgerCore
from agentcore.runtime.facts import LlmCallFact, NoteFact, RoundBoundaryFact, record_turn_fact
from agentcore.runtime.loop_controller import Intervention, LoopController
from agentcore.runtime.verify import finish_guard, format_guard_steer

from .directive import Continue, LoopDirective, Return, Rework
from .outcome import RoundOutcome
from .segments import tool_calls_to_dicts
from .stream import stream_llm_round
from .tool_clear import project_cleared_window
from .write_args_clear import project_cleared_write_args

logger = get_logger(__name__)


def record_round_start(*, round_idx: int, run_id: str, role: str) -> None:
    """Mark a ReAct round boundary for journal fold (§8.3)."""
    record_turn_fact(RoundBoundaryFact(round_idx=round_idx, run_id=run_id, role=role).to_fact())


def build_request_window(
    messages: list[LLMMessage],
    investigation_tools: frozenset[str],
    round_idx: int,
) -> list[LLMMessage]:
    """Project the LLM window with optional tool-result / write-args clearing."""
    window = messages
    if investigation_tools:
        cleared = project_cleared_window(
            window,
            clearable_tools=investigation_tools,
            keep_recent=settings.engine_tool_clear_keep_recent,
            min_chars=settings.engine_tool_clear_min_chars,
            summary_max_chars=settings.engine_tool_clear_file_read_summary_max_chars,
        )
        if cleared is not window:
            chars_saved = sum(
                len(old.content or "") - len(new.content or "")
                for old, new in zip(window, cleared, strict=True)
                if old.content != new.content
            )
            n_cleared = sum(
                1
                for old, new in zip(window, cleared, strict=True)
                if old.content != new.content
            )
            logger.info(
                "engine.tool_clear",
                cleared=n_cleared,
                chars_saved=chars_saved,
                round=round_idx,
            )
            window = cleared
    # Handoff 缓存崩塌：落盘后的 file_write 等大 body 仍在 assistant tool_calls.args，
    # 后续轮（含 handoff）整段 cache_miss。投影侧坍缩正文，canonical messages 不动。
    write_cleared = project_cleared_write_args(window, min_chars=500)
    if write_cleared is not window:
        n_writes = sum(
            1
            for old, new in zip(window, write_cleared, strict=True)
            if old is not new and old.role == "assistant"
        )
        logger.info(
            "engine.write_args_clear",
            cleared=n_writes,
            round=round_idx,
        )
        window = write_cleared
    return window


@dataclass(frozen=True)
class LlmRoundOutput:
    """Successful LLM round: streamed content, reasoning, and optional tool calls.

    ``aborted`` means the provider signaled a post-commit disconnect: the content
    / reasoning here are salvageable partials and the loop should finish DEGRADED
    rather than treating the round as a clean stop.
    """

    content: str
    reasoning: str
    tool_calls: list[Any]
    usage: TokenUsage | None
    empty_diagnosis: str | None = None
    empty_raw_preview: str | None = None
    aborted: bool = False


@dataclass(frozen=True)
class LlmRoundFailure:
    """LLM call failed on the non-raising path.

    Carries the ``(error_code, error_message)`` an SSE ``error`` event would show,
    but does NOT emit it: the loop defers surfacing the error until
    ``decide_llm_failure`` returns a terminal directive. The ``raise_on_error``
    (worker) path re-raises instead of returning this.
    """

    error_code: str
    error_message: str
    error_context: dict | None = None
    upstream_error: bool = False


async def run_llm_round(
    *,
    llm: OpenAICompatibleProvider,
    profile: ProfileParams,
    messages: list[LLMMessage],
    investigation_tools: frozenset[str],
    tool_defs: list[dict[str, Any]] | None,
    active_model: str | None,
    emit_content: Callable[[str], None],
    emit_reasoning: Callable[[str], None],
    on_tool_progress: Callable[[str, int], None] | None,
    round_idx: int,
    run_id: str,
    raise_on_error: bool,
    on_reset: Callable[[], None] | None = None,
) -> LlmRoundOutput | LlmRoundFailure:
    """Stream one LLM round; record facts and round_end log on success."""
    request_window = build_request_window(messages, investigation_tools, round_idx)
    request = build_request(
        profile,
        request_window,
        tools=tool_defs,
        tool_choice="auto" if tool_defs else "none",
        model=active_model,
    )
    from agentcore.runtime.runs.timeout_hard import mark_llm_inflight

    mark_llm_inflight(run_id, True)
    try:
        try:
            streamed = await stream_llm_round(
                llm,
                request,
                emit_content,
                emit_reasoning,
                on_tool_progress,
                on_reset=on_reset,
            )
        except Exception as e:
            # ``llm.call_failed`` is emitted by the leaf ``observe_provider`` fence
            # (or stream_closed on consumer cancel). Avoid a second emit here.
            if raise_on_error:
                raise
            code, message, context = error_fields_for(
                e,
                fallback_code=ErrorCode.LLM_ERROR,
                fallback_message="出了点问题，请稍后重试。",
            )
            return LlmRoundFailure(
                error_code=code,
                error_message=message,
                error_context=context,
                upstream_error=isinstance(e, LLMUpstreamError),
            )
    finally:
        mark_llm_inflight(run_id, False)

    round_content = streamed.content
    round_reasoning = streamed.reasoning
    round_tool_calls = streamed.tool_calls
    usage = streamed.usage
    empty_diagnosis = streamed.empty_diagnosis
    empty_raw_preview = streamed.empty_raw_preview

    record_turn_fact(
        LlmCallFact(
            run_id=run_id,
            round_idx=round_idx,
            content=round_content,
            reasoning_content=round_reasoning,
            tool_calls=tool_calls_to_dicts(round_tool_calls),
            usage=usage.as_dict() if usage else {},
            finish_reason=(
                "aborted"
                if streamed.aborted
                else ("tool_calls" if round_tool_calls else "stop")
            ),
        ).to_fact()
    )

    if streamed.aborted:
        logger.warning(
            "llm.stream_aborted",
            round=round_idx,
            content_chars=len(round_content),
            reasoning_chars=len(round_reasoning),
        )

    logger.info(
        "react.round_end",
        round=round_idx,
        tools=len(round_tool_calls) if round_tool_calls else 0,
        input_tokens=usage.input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        reasoning_tokens=usage.reasoning_tokens if usage else 0,
        done=not round_tool_calls and not streamed.aborted,
        aborted=streamed.aborted or None,
    )

    return LlmRoundOutput(
        content=round_content,
        reasoning=round_reasoning,
        tool_calls=round_tool_calls or [],
        usage=usage,
        empty_diagnosis=empty_diagnosis,
        empty_raw_preview=empty_raw_preview,
        aborted=streamed.aborted,
    )


def _citable_ids(
    turn_evidence_ledger: EvidenceLedgerCore | None,
) -> frozenset[str] | None:
    """``None`` = 未接通台账（不做 #rN 闸）；空 frozenset = 台账空（任何 #rN 均非法）。"""
    if turn_evidence_ledger is None:
        return None
    return turn_evidence_ledger.citable_ids()


def finish_guard_max_reworks(
    *,
    annotate_citations: bool,
    turn_evidence_ledger: EvidenceLedgerCore | None,
) -> int:
    """分路径回炉上限：调研 worker（有台账且不开 [n] 查）对齐辩论 O2 = 1；CEO 跟配置。"""
    if turn_evidence_ledger is not None and not annotate_citations:
        return 1
    return settings.engine_finish_guard_max_reworks


def decide_no_tool_round(
    outcome: RoundOutcome,
    *,
    final_content: str,
    controller: LoopController,
    annotate_citations: bool,
    citation_sink: list[dict[str, Any]] | None,
    finish_guard_reworks: int,
    tools_offered: bool = False,
    supports_tools: bool | None = None,
    turn_evidence_ledger: EvidenceLedgerCore | None = None,
) -> LoopDirective:
    """Pick the directive for a round with no tool calls.

    A round that produced text either finishes cleanly (``Return``) or, if
    finish_guard rejects it and reworks remain, is reworked (``Rework``). An empty
    round walks the convergence controller's degraded ladder: finish degraded
    (``Return`` + DEGRADED) or retry on the same model (``Continue``).
    """
    if outcome.content:
        reworks = finish_guard(
            final_content,
            citation_count=len(citation_sink or []),
            check_citations=annotate_citations,
            citable_ids=_citable_ids(turn_evidence_ledger),
        )
        max_reworks = finish_guard_max_reworks(
            annotate_citations=annotate_citations,
            turn_evidence_ledger=turn_evidence_ledger,
        )
        if reworks and finish_guard_reworks < max_reworks:
            return Rework()
        return Return()

    action = controller.empty_response_action()
    if action is Intervention.FINALIZE:
        logger.warning("engine.degraded")
        if tools_offered and supports_tools is False and not outcome.content:
            return Return(
                finish_reason=FinishReason.ERROR,
                extra_content=TOOLS_UNAVAILABLE_RUNTIME_MESSAGE,
            )
        return Return(finish_reason=FinishReason.DEGRADED)
    return Continue()


def apply_finish_guard_rework(
    *,
    messages: list[LLMMessage],
    emit_reset: Callable[[str], None],
    final_content: str,
    content_before_round: str,
    round_idx: int,
    run_id: str,
    annotate_citations: bool,
    citation_sink: list[dict[str, Any]] | None,
    finish_guard_reworks: int,
    turn_evidence_ledger: EvidenceLedgerCore | None = None,
) -> tuple[str, int]:
    """Discard rejected content, inject steer, return updated content and rework count.

    ``emit_reset`` clears the producer's already-streamed draft on the right surface —
    ``content_reset`` for the CEO bubble, ``run_output_reset`` for a worker card — so the
    rewrite presents as a clean「违规版 → 修正版」replacement, not an append (统一底线).
    reason=``finish_guard`` is the ONLY reset that folds into the「已按交付规范重写」chip."""
    reworks = finish_guard(
        final_content,
        citation_count=len(citation_sink or []),
        check_citations=annotate_citations,
        citable_ids=_citable_ids(turn_evidence_ledger),
    )
    steer = format_guard_steer(reworks)
    logger.info(
        "engine.finish_guard_rework",
        round=round_idx,
        attempt=finish_guard_reworks + 1,
        issues=len(reworks),
    )
    emit_reset("finish_guard")
    messages.append(LLMMessage(role="user", content=steer))
    record_turn_fact(
        NoteFact(
            role="user",
            content=steer,
            reason="finish_guard",
            run_id=run_id,
        ).to_fact()
    )
    return content_before_round, finish_guard_reworks + 1


def apply_exit_ledger_ref_strip(
    content: str,
    *,
    turn_evidence_ledger: EvidenceLedgerCore | None,
    emit_reset: Callable[[str], None],
    emit_content: Callable[[str], None],
    run_id: str = "",
) -> str:
    """回炉耗尽后剥离非法 ``#rN``（Q3：放行 + 必发观测，禁止静默）。

    若正文被改写：``finish_guard`` reset 清空已流式草稿，再把剥离后正文作为新 delta
    推上对应表面（对齐辩论 evidence demote）。
    """
    citable = _citable_ids(turn_evidence_ledger)
    bad = invalid_ledger_ref_ids(content, citable)
    if not bad:
        return content
    cleaned = strip_invalid_ledger_refs(content, set(bad))
    logger.warning(
        "citations.invalid_ledger_ref",
        run_id=run_id or None,
        markers=bad,
        citable_count=len(citable or ()),
    )
    if cleaned != content:
        emit_reset("finish_guard")
        emit_content(cleaned)
    return cleaned
