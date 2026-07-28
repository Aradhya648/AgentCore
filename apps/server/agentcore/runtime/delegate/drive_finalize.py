"""Post-wave finalize: metrics, pause/boundary, partial fail, criteria, CEO result."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolEffect
from agentcore.runtime.delegate.accumulate import (
    accumulate_usage,
    collect_citations,
    collect_ledger,
    register_sessions,
)
from agentcore.runtime.delegate.ceo_format import direct_result, format_for_ceo
from agentcore.runtime.delegate.delivery_status import maybe_emit_delivery_status
from agentcore.runtime.delegate.drive_terminal import post_session_all_completed
from agentcore.runtime.delegate.nesting import absorb_children
from agentcore.runtime.delegate.supervised import (
    SupervisedRun,
    format_boundary_for_ceo,
)
from agentcore.runtime.events import batch_metrics as batch_metrics_event
from agentcore.runtime.runs.constants import DELEGATE_OUTPUT_LIMIT
from agentcore.tools.protocol import ToolResult

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import BatchMetrics, RunState

type DelegateTool = Any

logger = get_logger(__name__)


def emit_batch_metrics(
    tool: DelegateTool,
    batch_metrics: list[BatchMetrics],
    *,
    execution_id: str,
    call_idx: int,
    complexity_hint: str,
) -> None:
    if not batch_metrics:
        return
    m = batch_metrics[0]
    logger.info(
        "delegate.completed",
        call=call_idx,
        hint=complexity_hint,
        nodes=m.nodes,
        width=m.width,
        peak=m.peak_running,
        wall_ms=m.wall_ms,
        busy_ms=m.busy_ms,
        avg_parallelism=round(m.busy_ms / m.wall_ms, 2) if m.wall_ms else 0.0,
        slot_starved=m.slot_starved,
        completed=m.completed,
        failed=m.failed,
        skipped=m.skipped,
        # 受监督波循环埋点 (执行引擎架构设计.md §受监督的波循环): boundary fires this segment +
        # scope 信号占比 (derived from raw counts, mirroring avg_parallelism).
        bind=m.bind_boundaries,
        scope=m.scope_boundaries,
        checkpoint=m.checkpoint_boundaries,
        escalations=m.escalations,
        scope_ratio=round(m.scope_escalations / m.escalations, 2) if m.escalations else 0.0,
    )
    # 协作质量 tally (学·度量 §2.5): fold this batch's drift + escalation signals into the
    # turn-level roll-up on the accumulator (rolls up to the captain via absorb_children).
    tool._acc.collab["scope_signals"] += m.scope_escalations
    tool._acc.collab["escalations"] += m.escalations
    # 深层诊断指标 (前端UX设计.md §十): surface the scheduler snapshot to the client so
    # 诊断模式 shows it in run detail (journaled → replays on reload). Whole-batch verbatim
    # — the host already logged it; this just also hands it to the UI fold.
    tool._sink.emit(
        batch_metrics_event(execution_id=execution_id, metrics=dataclasses.asdict(m))
    )


def handle_pending_pause(
    tool: DelegateTool,
    *,
    session: Any,
    call_idx: int,
    results: dict[str, RunState],
) -> ToolResult | None:
    """Soft pause after checkpoint YIELD. None → continue finalize."""
    # 挂起即收口 (②): the checkpoint boundary persisted a resume frame and YIELDed (soft
    # pause). End the turn here with a SUSPEND ToolResult — the engine maps it to
    # FinishReason.PAUSED, leaves the delegate call pending (no result), and the persist
    # tail parks the turn (the frame is the record). The已完成 workers' usage / ledger /
    # citations are NOT folded here: they ride the durable frame's ``completed`` and bill
    # on the cold resume drive — matching the disconnect→resume path this collapses onto.
    #
    # 协调态例外：host 靠 ``_pending_pause`` / ``_pending_boundary`` 投递 BOUNDARY_YIELD。
    # 若此处清掉标志，host 永远看不到（竞态）。协调路径保留标志、不 SUSPEND、不收口回合。
    if not tool._pending_pause:
        return None
    if session is not None:
        logger.info("delegate.coord_pause_signal", call=call_idx, completed=len(results))
        return ToolResult(tool_call_id="", success=True, output="")
    tool._pending_pause = False
    logger.info("delegate.paused", call=call_idx, completed=len(results))
    return ToolResult(tool_call_id="", success=True, output="", effect=ToolEffect.SUSPEND)


def handle_pending_boundary(
    tool: DelegateTool,
    plan: RunPlan,
    results: dict[str, RunState],
    *,
    execution_id: str,
    finalize: bool,
    session: Any,
    call_idx: int,
) -> ToolResult | None:
    """Supervised boundary yield. None → continue finalize."""
    from agentcore.runtime.runs import BoundaryReason

    if tool._pending_boundary is None:
        return None
    reason, nodes = tool._pending_boundary
    # 单一事实源 (P5 持久化): a SCOPE yield marked the deviating nodes' escalations
    # ``consumed`` IN PLACE (wave.py). Re-journal their terminal RunState so
    # ``completed_from_journal`` rebuilds the resume seed WITH ``consumed`` — else a
    # durable re-drive (a later checkpoint pause + resume of the same plan) would
    # re-fire an already-handled SCOPE boundary. Last-write-wins per run_id makes the
    # refreshed message_final supersede the pre-consumption one.
    if reason is BoundaryReason.SCOPE:
        from agentcore.runtime.facts import record_turn_fact
        from agentcore.runtime.runs.serialize import run_final_fact

        for node in nodes:
            state = results.get(node.run_id)
            if state is not None:
                record_turn_fact(run_final_fact(node.run_id, state))
    tool._supervised = SupervisedRun(
        plan=plan,
        completed=dict(results),
        execution_id=execution_id,
        finalize=finalize,
        reason=reason,
        boundary_run_ids=[n.run_id for n in nodes],
    )
    # 协作质量 tally (学·度量 §2.5, 首计划存活): a supervised boundary handed control back
    # to the captain mid-plan — the opening plan did not run start-to-finish untouched.
    tool._acc.collab["boundary_yields"] += 1
    logger.info(
        "delegate.yielded",
        call=call_idx,
        reason=reason.value,
        boundary=[n.run_id for n in nodes],
        completed=len(results),
    )
    brief = format_boundary_for_ceo(tool, reason, plan, results, nodes)
    if session is not None:
        # Leave ``_pending_boundary`` for host to post BOUNDARY_YIELD + clear.
        return ToolResult(
            tool_call_id="",
            success=True,
            output=brief,
            output_limit=DELEGATE_OUTPUT_LIMIT,
        )
    tool._pending_boundary = None
    return ToolResult(
        tool_call_id="",
        success=True,
        output=brief,
        output_limit=DELEGATE_OUTPUT_LIMIT,
    )


def handle_partial_failure(
    tool: DelegateTool,
    plan: RunPlan,
    results: dict[str, RunState],
    *,
    execution_id: str,
    finalize: bool,
    seed_completed: dict[str, RunState] | None,
    session: Any,
    call_idx: int,
) -> ToolResult | None:
    """Stash plan on THIS-segment FAILED/SKIPPED. None → continue finalize."""
    from agentcore.runtime.runs import BoundaryReason, RunPhase

    # Partial failure: all nodes terminal but some FAILED / SKIPPED — stash the plan so the
    # CEO can replan(add=...) replacement nodes on the SAME DAG (not a fresh delegate).
    # Usage / ledger / citations fold on the resume or dispose path (same as boundary yield).
    # Only failures from THIS drive segment count — nodes already FAILED/SKIPPED in
    # ``seed_completed`` (a replan resume) must not re-trigger stash.
    seeded_ids = set(seed_completed or ())
    failed_nodes = [
        n
        for n in plan.nodes
        if (st := results.get(n.run_id)) is not None
        and st.phase in (RunPhase.FAILED, RunPhase.SKIPPED)
        and n.run_id not in seeded_ids
    ]
    if not failed_nodes or tool._supervised is not None:
        return None
    tool._supervised = SupervisedRun(
        plan=plan,
        completed=dict(results),
        execution_id=execution_id,
        finalize=finalize,
        reason=BoundaryReason.SCOPE,
        boundary_run_ids=[n.run_id for n in failed_nodes],
    )
    logger.info(
        "delegate.partial_failure_stashed",
        call=call_idx,
        failed=[n.run_id for n in failed_nodes],
        completed=len(results),
    )
    # 交付状态（诚实对账）：部分失败也是一次收尾——把已落盘 / 缺口如实发给用户；
    # CEO 若 replan 补跑，补跑后的收尾会以同 execution_id 覆盖为最新对账。
    maybe_emit_delivery_status(
        tool._sink,
        plan,
        results,
        execution_id=execution_id,
        backend=tool._base_tool_context.backend,
    )
    partial_output = format_for_ceo(tool, plan, results, call_idx=call_idx)
    # Coordination terminal: workers are all marked done; without ALL_COMPLETED the
    # CEO idle-waits the full coordination timeout (same class of bug as criteria gap).
    if session is not None:
        post_session_all_completed(session, output=partial_output)
    from agentcore.runtime.delegate.delivery_status import build_delivery_status

    delivery_meta = build_delivery_status(
        plan,
        results,
        execution_id=execution_id,
        backend=tool._base_tool_context.backend,
    )
    return ToolResult(
        tool_call_id="",
        success=True,
        output=partial_output,
        output_limit=DELEGATE_OUTPUT_LIMIT,
        # Keep success=True (avoid CEO retry storms) but attach structured delivery
        # meta so the CEO / presentation layer sees COMPLETED_WITH_GAPS honesty.
        metadata={
            "delivery": delivery_meta
            or {"state": "partial", "gaps": [], "execution_id": execution_id},
            "partial_failure": True,
            "failed_run_ids": [n.run_id for n in failed_nodes],
        },
    )


async def finalize_successful_drive(
    tool: DelegateTool,
    plan: RunPlan,
    results: dict[str, RunState],
    *,
    execution_id: str,
    finalize: bool,
    completion_criteria: Any,
    session: Any,
    call_idx: int,
) -> ToolResult:
    """Accumulate products, check criteria, emit delivery, fold CEO ToolResult."""
    from agentcore.runtime.costing import usage_metadata
    from agentcore.runtime.delegate.completion import (
        check_delegate_completion,
        collect_delivered_files,
        format_completion_gap_message,
        gap_fingerprint,
        resolve_completion_with_source,
    )
    from agentcore.runtime.runs import RunPhase

    # §十一 来源卡接入 (方案①, 远期规划.md §4.5): snapshot the turn-accumulated sources
    # BEFORE folding this call's workers in, so the slice below is exactly THIS delegate call's
    # NEW (deduped) web sources — including any nested sub-team absorbed just after. Carrying
    # them on the ToolResult lets the CEO-path execute_tools number them into the turn's source
    # cards AND fold each [n]=url back into THIS tool message, so the CEO can cite a worker-found
    # 法条 by a card-aligned [n] (Gap A). merge_citations dedups by url, so the turn-close
    # backstop merge (pipeline.run / resume.finish) re-folds the same sources as a no-op — one
    # numbering source, stable card indices across calls, no reconciliation patch.
    citations_before = len(tool._acc.citations)
    call_usage = accumulate_usage(tool, results)
    collect_ledger(tool, plan, results)
    collect_citations(tool, results)
    registered = register_sessions(tool, plan, results)
    if tool._session_saver is not None:
        for run_session in registered:
            await tool._session_saver(run_session)
    absorb_children(tool)
    new_citations = tool._acc.citations[citations_before:]

    resolved = resolve_completion_with_source(
        completion_criteria,
        plan,
        suppress_structured_files_written=bool(
            tool._base_tool_context.cold_start_explore_pending
        ),
    )
    criteria = resolved.criteria
    # Preload source texts for graph_consistent (async backend.read).
    file_map: dict[str, str] = {}
    backend = tool._base_tool_context.backend
    if backend is not None:
        from agentcore.runtime.delegate.completion import (
            _batch_landed_graph_sources,
            _collect_graph_source_paths,
        )
        from agentcore.runtime.delegate.graph_integrity import load_source_file_map
        from agentcore.runtime.runs import RunPhase as _RunPhase

        completed = [
            s for s in results.values() if s.phase is _RunPhase.COMPLETED
        ]
        need_graph = (
            (criteria is not None and criteria.kind == "graph_consistent")
            or (
                (criteria is None or criteria.kind != "runtime_ready")
                and _batch_landed_graph_sources(completed)
            )
        )
        if need_graph:
            file_map = await load_source_file_map(
                backend, _collect_graph_source_paths(completed)
            )
    criteria_ok, gaps = check_delegate_completion(
        criteria, results, backend=backend, file_map=file_map or None
    )
    if not criteria_ok:
        delivered = collect_delivered_files(results)
        kind_for_fp = criteria.kind if criteria is not None else "typescript_verify"
        fp = gap_fingerprint(kind_for_fp, gaps)
        streak = tool.note_completion_gap(fp)
        escalate = streak >= 2
        gap_msg = format_completion_gap_message(
            gaps,
            criteria_kind=kind_for_fp,
            source=resolved.source or "structured",
            escalate=escalate,
            delivered_files=delivered,
        )
        logger.info(
            "delegate.completion_criteria_unmet",
            criteria=kind_for_fp,
            source=resolved.source or "structured",
            gaps=gaps,
            streak=streak,
            escalate=escalate,
            delivered_files=delivered[:24],
            execution_id=execution_id,
        )
        # 交付状态（诚实对账）：验收未满足即是用户可见的交付缺口，连同批次级
        # criteria 缺口一起结构化发出（含可推导的 bind_local_folder 行动项）。
        maybe_emit_delivery_status(
            tool._sink,
            plan,
            results,
            execution_id=execution_id,
            backend=tool._base_tool_context.backend,
            criteria_gaps=gaps,
        )
        # Same terminal post as the success path — criteria gap is still end-of-batch,
        # but must not present as failed=0 success（交付真相）.
        failed_n = sum(
            1 for s in results.values() if s.phase is RunPhase.FAILED
        )
        if session is not None:
            post_session_all_completed(
                session,
                output=gap_msg,
                criteria_met=False,
                failed=failed_n,
            )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=gap_msg,
            output_limit=DELEGATE_OUTPUT_LIMIT,
            metadata={
                **(usage_metadata(call_usage) or {}),
                "criteria_unmet": True,
                "failed": failed_n,
            },
            citations=new_citations or None,
        )

    tool.clear_completion_gap_streak()

    # 交付状态（诚实对账）：正常收尾（含 finalize 单人直出）——有落盘文件或缺口才发，
    # 纯 prose 成功批次保持无声。放在 direct_result / format_for_ceo 分叉之前，两条
    # 收尾路径共用这一次发射。
    maybe_emit_delivery_status(
        tool._sink,
        plan,
        results,
        execution_id=execution_id,
        backend=tool._base_tool_context.backend,
    )

    if finalize and len(plan.nodes) == 1:
        only = results.get(plan.nodes[0].run_id)
        if only and only.phase is RunPhase.COMPLETED and only.content.strip():
            if session is not None:
                post_session_all_completed(
                    session,
                    output=only.content,
                    completed=1,
                    total=1,
                    output_limit=2000,
                )
            return direct_result(tool, only)

    output = format_for_ceo(tool, plan, results, call_idx=call_idx)
    if session is not None:
        post_session_all_completed(session, output=output)
    return ToolResult(
        tool_call_id="",
        success=True,
        output=output,
        output_limit=DELEGATE_OUTPUT_LIMIT,
        metadata=usage_metadata(call_usage),
        citations=new_citations or None,
    )


async def finalize_drive(
    tool: DelegateTool,
    plan: RunPlan,
    results: dict[str, RunState],
    *,
    execution_id: str,
    finalize: bool,
    seed_completed: dict[str, RunState] | None,
    completion_criteria: Any,
    session: Any,
    call_idx: int,
    complexity_hint: str,
    batch_metrics: list[BatchMetrics],
) -> ToolResult:
    """Full post-wave finalize pipeline (metrics → early exits → success)."""
    # Thrash rebrand memory before early exits (pause / partial) so cold re-delegate
    # in the same conversation still sees DEGRADED/ceiling_backstop workers.
    from agentcore.runtime.coordination.thrash import record_thrashing_from_results

    record_thrashing_from_results(
        conversation_id=str(getattr(tool, "_conversation_id", None) or ""),
        plan=plan,
        results=results,
    )
    emit_batch_metrics(
        tool,
        batch_metrics,
        execution_id=execution_id,
        call_idx=call_idx,
        complexity_hint=complexity_hint,
    )
    paused = handle_pending_pause(
        tool, session=session, call_idx=call_idx, results=results
    )
    if paused is not None:
        return paused
    boundary = handle_pending_boundary(
        tool,
        plan,
        results,
        execution_id=execution_id,
        finalize=finalize,
        session=session,
        call_idx=call_idx,
    )
    if boundary is not None:
        return boundary
    partial = handle_partial_failure(
        tool,
        plan,
        results,
        execution_id=execution_id,
        finalize=finalize,
        seed_completed=seed_completed,
        session=session,
        call_idx=call_idx,
    )
    if partial is not None:
        return partial
    return await finalize_successful_drive(
        tool,
        plan,
        results,
        execution_id=execution_id,
        finalize=finalize,
        completion_criteria=completion_criteria,
        session=session,
        call_idx=call_idx,
    )
