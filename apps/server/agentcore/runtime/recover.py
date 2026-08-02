"""Single recover primitive: journal projection → seed WaveScheduler → settle / redrive.

Resume (plan_review / team_preview / ask_user) and crash redrive both route here.
The journal remains the唯一事实源; :class:`~agentcore.runtime.turn_state.TurnState`
is the sole projection entry.

Backlog (not this iteration):
- Write-tool idempotency keys — crash redrive may re-run in-flight workers
  (``file_write`` overwrite semantics are accepted for now).
- Cross-process Redis lease backend (Postgres this iteration).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, NamedTuple

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolEffect
from agentcore.runtime.checkpoints import CheckpointDecision, CheckpointResponse
from agentcore.runtime.events import (
    EventSink,
    checkpoint_resolved,
    plan_review_resolved,
    team_preview_resolved,
)
from agentcore.runtime.suspension import (
    AskUserSuspension,
    PlanReviewSuspension,
    TeamPreviewSuspension,
    TurnSuspension,
)
from agentcore.runtime.turn_state import TurnState
from agentcore.tools.builtin.ask_user.schema import option_label

if TYPE_CHECKING:
    from agentcore.db.models.runs import TurnLeaseRow
    from agentcore.tools.builtin.debate import DebateTool
    from agentcore.tools.builtin.delegate import DelegateTool

logger = get_logger(__name__)


class SettledSuspension(NamedTuple):
    """Outcome of recover/settle — tool result text (+ optional terminal reply).

    ``effect`` mirrors the settled tool's :class:`ToolEffect` so the cold resume
    path can honor re-entrant SUSPEND (downstream checkpoint while ``resume_plan``
    runs) the same way the live engine does — PAUSED, no CEO continuation.
    ``terminal_text`` remains the ask_user-stop in-band closing path (INTERACT).
    """

    output: str
    terminal_text: str | None
    effect: ToolEffect = ToolEffect.CONTINUE


async def recover_turn(
    *,
    state: TurnState,
    sink: EventSink,
    delegate_tool: DelegateTool,
    execution_id: str,
    suspension: TurnSuspension | None = None,
    decision: CheckpointDecision | None = None,
    note: str = "",
    selected: list[str] | None = None,
    style_id: str | None = None,
    format_id: str | None = None,
    debate_tool: DebateTool | None = None,
) -> SettledSuspension:
    """Settle a resume decision or CONTINUE-redrive unfinished DAG from ``state``.

    - With ``suspension`` + ``decision``: resume three kinds (behaviour-equivalent to
      the former ``settle_resumed_suspension``).
    - Without suspension (crash): ``decision`` defaults to CONTINUE; redrives unfinished
      plan nodes with ``seed_completed=state.completed`` (completed nodes skipped).
    - ``debate_tool`` is required when settling a ``team_preview`` with
      ``primitive=debate``.
    """
    if suspension is not None:
        if decision is None:
            raise ValueError("recover_turn resume requires decision")
        return await _settle_resume(
            suspension,
            state=state,
            decision=decision,
            note=note,
            selected=selected or [],
            style_id=style_id,
            format_id=format_id,
            sink=sink,
            delegate_tool=delegate_tool,
            debate_tool=debate_tool,
            execution_id=execution_id,
        )

    decision = decision or CheckpointDecision.CONTINUE
    plan = state.plan
    if plan is None:
        raise ValueError("recover_turn crash redrive requires a plan projection")
    eid = state.execution_id or execution_id
    seed = dict(state.completed)
    # Crash mid-flight teams were typically wall-coordinated (≥2 workers). Align the
    # redrive with that product default — resume_plan's coordinate default is False
    # (classic / plan_review), which would silently strip note-wall semantics.
    logger.info(
        "recover.crash_redrive",
        execution_id=eid,
        completed=len(seed),
        unfinished=len(state.unfinished_run_ids),
        decision=decision.value,
        coordinate=True,
        coordination="wall",
    )
    delegate_result = await delegate_tool.resume_plan(
        plan,
        seed,
        decision=decision,
        note=note,
        checkpoint_run_ids=set(),
        execution_id=eid,
        coordinate=True,
        coordination="wall",
    )
    return SettledSuspension(delegate_result.output, None, delegate_result.effect)


async def _settle_resume(
    suspension: TurnSuspension,
    *,
    state: TurnState,
    decision: CheckpointDecision,
    note: str,
    selected: list[str],
    style_id: str | None,
    format_id: str | None,
    sink: EventSink,
    delegate_tool: DelegateTool,
    debate_tool: DebateTool | None,
    execution_id: str,
) -> SettledSuspension:
    """Kind-specific resume settle, projecting exclusively via ``state``."""
    # research_first 仅辩论开工卡合法；其它挂起点降级为 STOP，不得静默 continue。
    if decision is CheckpointDecision.RESEARCH_FIRST and not (
        isinstance(suspension, TeamPreviewSuspension) and suspension.primitive == "debate"
    ):
        logger.warning(
            "team_preview.research_first_rejected",
            kind=getattr(suspension.kind, "value", suspension.kind),
            primitive=getattr(suspension, "primitive", None),
        )
        decision = CheckpointDecision.STOP

    if isinstance(suspension, AskUserSuspension):
        response = CheckpointResponse(
            decision=decision,
            note=note,
            selected=list(selected),
            style_id=(style_id or "").strip(),
            format_id=(format_id or "").strip(),
        )
        allowed = {option_label(o) for q in suspension.questions for o in q.get("options", [])}
        response.selected = [s for s in response.selected if s in allowed]
        if (
            suspension.intent == "organize_plan"
            and response.decision is CheckpointDecision.CONTINUE
        ):
            from agentcore.tools.builtin.ask_user.card import option_to_organize_op
            from agentcore.workspace.organize_plan_store import register_plan

            kept: list[dict] = []
            for q in suspension.questions:
                for o in q.get("options") or []:
                    if not isinstance(o, dict):
                        continue
                    if option_label(o) not in response.selected:
                        continue
                    op = option_to_organize_op(o)
                    if op:
                        kept.append(op)
            register_plan(
                plan_id=suspension.checkpoint_id,
                conversation_id=suspension.conversation_id,
                operations=kept,
            )
        daily_review_apply = None
        if suspension.intent == "daily_review" and response.decision is CheckpointDecision.CONTINUE:
            from agentcore.standing_tasks.review_apply import (
                apply_daily_review_selections,
            )

            daily_review_apply = await apply_daily_review_selections(
                user_id=suspension.user_id,
                folder_id=suspension.folder_id or "",
                conversation_id=suspension.conversation_id,
                questions=list(suspension.questions or []),
                selected_labels=list(response.selected),
            )
        sink.emit(
            checkpoint_resolved(
                checkpoint_id=suspension.checkpoint_id,
                decision=response.decision.value,
                note=response.note,
                selected=response.selected,
            )
        )
        from agentcore.runtime.coordination.session import (
            CoordinationSession,
            current_execution_id,
            set_active_coordination,
        )

        snap = state.coordination
        if snap is not None and snap.active:
            session = CoordinationSession.from_snapshot(snap)
            plan = state.plan
            seed = dict(state.completed)
            for rid in seed:
                session.mark_worker_completed(rid)
            unfinished = plan is not None and any(n.run_id not in seed for n in plan.nodes)
            if snap.execution_id:
                current_execution_id.set(snap.execution_id)
                base_ctx = getattr(delegate_tool, "_base_tool_context", None)
                if base_ctx is not None:
                    base_ctx.execution_id = snap.execution_id
            if unfinished and plan is not None:
                from agentcore.runtime.coordination.host import try_start_coordination

                try_start_coordination(
                    delegate_tool,
                    plan,
                    execution_id=snap.execution_id,
                    seed_completed=seed,
                    finalize=False,
                    seed_notes=None,
                    complexity_hint="standard",
                    # Prefer the in-process mode from the live tool; missing (process
                    # restart) → wall so mid-flight teams keep the prior default.
                    coordination=getattr(delegate_tool, "_coordination", None) or "wall",
                    call_idx=0,
                    completion_criteria=None,
                    coordinate=True,
                    session=session,
                )
            else:
                set_active_coordination(session)
        from agentcore.tools.builtin.ask_user import ask_user_tool_result
        from agentcore.tools.builtin.ask_user.result import (
            ask_user_daily_review_result,
            ask_user_organize_plan_result,
        )

        if suspension.intent == "organize_plan":
            from agentcore.workspace.organize_plan_store import get_plan

            org_plan = get_plan(suspension.checkpoint_id)
            kept_n = len(org_plan.operations) if org_plan else 0
            result = ask_user_organize_plan_result(
                response,
                plan_id=suspension.checkpoint_id,
                kept_count=kept_n,
            )
        elif suspension.intent == "daily_review":
            applied = daily_review_apply.applied if daily_review_apply else 0
            skipped = daily_review_apply.skipped if daily_review_apply else 0
            errors = daily_review_apply.errors if daily_review_apply else ()
            result = ask_user_daily_review_result(
                response,
                applied=applied,
                skipped=skipped,
                errors=errors,
            )
        else:
            result = ask_user_tool_result(response)
            # 场面账（style / presentation_format / automation_delivery）已拆除：
            # resume 不再 record_*；DESIGN 默认风格由 design_prompt_block 软注入。
        terminal = result.final_text if result.effect is ToolEffect.INTERACT else None
        return SettledSuspension(result.output, terminal, result.effect)

    if isinstance(suspension, PlanReviewSuspension):
        sink.emit(
            plan_review_resolved(
                checkpoint_id=suspension.checkpoint_id,
                decision=decision.value,
                note=note,
            )
        )
        logger.info(
            "plan_review.resolved",
            checkpoint_id=suspension.checkpoint_id,
            decision=decision.value,
        )
        seed_completed = dict(state.completed) or suspension.completed
        plan = state.plan or suspension.plan
        eid = state.execution_id or execution_id
        delegate_result = await delegate_tool.resume_plan(
            plan,
            seed_completed,
            decision=decision,
            note=note,
            checkpoint_run_ids=suspension.checkpoint_run_ids,
            execution_id=eid,
            # 帧回灌批次协作参数：恢复用全新 DelegateTool（_coordination 缺省 none），
            # 不回灌则复核后续波次的 worker 被剥便签三件套。
            coordination=suspension.coordination,
            team_brief=suspension.team_brief,
            # CONTINUE 时读帧上 ceo_review → llm 压缩注入 gate_notes（deterministic 不下发）。
            ceo_review=suspension.ceo_review,
        )
        return SettledSuspension(delegate_result.output, None, delegate_result.effect)

    if isinstance(suspension, TeamPreviewSuspension):
        sink.emit(
            team_preview_resolved(
                checkpoint_id=suspension.checkpoint_id,
                decision=decision.value,
                note=note,
            )
        )
        logger.info(
            "team_preview.resolved",
            checkpoint_id=suspension.checkpoint_id,
            decision=decision.value,
            primitive=suspension.primitive,
        )
        if suspension.primitive == "debate":
            if debate_tool is None:
                raise ValueError("recover_turn debate kickoff requires debate_tool")
            debate_result = await debate_tool.resume_after_kickoff(
                decision=decision,
                note=note,
                arguments=dict(suspension.debate_arguments),
            )
            # STOP / RESEARCH_FIRST：tool result 回灌 CEO 续跑（terminal_text=None）。
            return SettledSuspension(debate_result.output, None, debate_result.effect)

        seed_completed = dict(state.completed) or suspension.completed
        plan = state.plan or suspension.plan
        eid = state.execution_id or execution_id
        # Preview hung before the coordinate fork; CONTINUE/ADJUST must arm the
        # background scheduler (product default for ≥2 workers).
        # RESEARCH_FIRST 已在入口降级为 STOP，不会静默开做。
        delegate_result = await delegate_tool.resume_plan(
            plan,
            seed_completed,
            decision=decision,
            note=note,
            checkpoint_run_ids=suspension.checkpoint_run_ids,
            execution_id=eid,
            coordinate=True,
            apply_kickoff_grant=True,
            # 帧回灌批次协作参数：开工卡挂在 setup_note_wall 之前，coordination /
            # team_brief / seed_notes 只存在帧里；不回灌则 wall 批降级 none（worker
            # 无便签三件套、CEO 预贴便签丢失）——2026-07-20 P2 手驱真跑抓获。
            coordination=suspension.coordination,
            team_brief=suspension.team_brief,
            seed_notes=list(suspension.seed_notes),
        )
        return SettledSuspension(delegate_result.output, None, delegate_result.effect)

    raise ValueError(f"unknown suspension kind: {suspension.kind!r}")


async def _await_crash_redrive_drive(execution_id: str) -> None:
    """When crash redrive arms wall coordination, wait for the background drive.

    ``resume_plan(coordinate=True)`` returns as soon as the scheduler is armed; the
    sweeper must keep the recovering lease (+ heartbeat) until workers settle, else
    the lease is released mid-flight and the next sweep reclaims a still-open DAG.

    Called **outside** ``turn_lease_recover_timeout_seconds`` (that budget only
    covers orphan + factory + arm).
    """
    from agentcore.runtime.coordination.session import active_coordination

    session = active_coordination(execution_id)
    task = getattr(session, "drive_task", None) if session is not None else None
    if task is None or task.done():
        return
    await task


async def recover_expired_lease(lease: TurnLeaseRow, state: TurnState) -> None:
    """Background entry for the sweeper: orphan hot pending, then redrive unfinished DAG.

    When crash redrive is unavailable (unwired factory / hard failure), degrade to an
    honest ``interrupted`` terminal via lease salvage — never leave a fake pause.

    Lease is released only after a successful recover or salvage. Salvage failure
    re-orphans the row so the next sweep can retry (never delete without ``turn_end``).

    ``turn_lease_recover_timeout_seconds`` only bounds orphan + factory +
    ``recover_turn`` (to arm). After arm, heartbeat stays up while awaiting drive;
    ``turn_lease_recover_max_attempts`` still caps ready cycles — no ready-only loop.
    """
    from agentcore.config import settings
    from agentcore.core.types import new_id
    from agentcore.runtime.coordination.session import cancel_coordination_on_user_stop
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.interaction_orphan import orphan_turn_before_recover
    from agentcore.runtime.leases.service import (
        heartbeat_turn_lease,
        lease_heartbeat_loop,
        lease_owner_id,
        orphan_turn_lease,
        release_turn_lease,
    )
    from agentcore.runtime.leases.sweeper import salvage_interrupted_turn
    from agentcore.runtime.turn_interrupt import TurnInterruptReason

    message_id = lease.message_id
    conversation_id = lease.conversation_id
    meta = getattr(lease, "meta", None)
    meta_dict = dict(meta) if isinstance(meta, dict) else {}
    trace_id = getattr(lease, "trace_id", None)
    if trace_id is None:
        trace_id = meta_dict.get("trace_id")
    attempts = int(meta_dict.get("recover_attempts") or 0)
    should_release = False
    lease_stop: asyncio.Event | None = None
    heartbeat_task: asyncio.Task | None = None
    # Prefer journal execution_id so timeout/cancel can stop leftover coordination.
    eid: str | None = state.execution_id

    def _stop_background() -> None:
        """Hard-stop workers + drive before salvage (not ask_user soft_stop)."""
        stop_eid = (eid or "").strip()
        if not stop_eid:
            return
        with contextlib.suppress(Exception):
            cancel_coordination_on_user_stop(execution_id=stop_eid)

    async def _salvage(*, reason: str, event: str) -> bool:
        logger.warning(
            event,
            message_id=message_id,
            conversation_id=conversation_id,
            attempts=attempts,
        )
        return await salvage_interrupted_turn(
            message_id=message_id,
            conversation_id=conversation_id,
            trace_id=trace_id if isinstance(trace_id, str) else None,
            reason=reason,
        )

    try:
        # Cap ready loops: another claim after a hung/cancelled recover must not spin.
        max_attempts = max(1, int(settings.turn_lease_recover_max_attempts))
        if attempts > max_attempts:
            should_release = await _salvage(
                reason=TurnInterruptReason.REDRIVE_FAILED.value,
                event="recover.lease_stalled",
            )
            return

        # Heartbeat covers rebuild/arm and the post-arm await-drive window.
        owner = lease_owner_id()
        await heartbeat_turn_lease(message_id, owner_id=owner, phase="recovering")
        lease_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            lease_heartbeat_loop(
                message_id,
                owner_id=owner,
                interval_seconds=settings.turn_lease_heartbeat_seconds,
                stop=lease_stop,
                phase="recovering",
            ),
            name=f"recover-lease-hb-{message_id}",
        )

        timeout = float(settings.turn_lease_recover_timeout_seconds)

        async def _arm_redrive() -> str | None:
            """Orphan + factory + recover_turn to arm. Returns eid, or None if salvaged."""
            nonlocal should_release, eid
            # D6：先 orphan 热路 pending，再 recover 重驱
            await orphan_turn_before_recover(
                turn_id=message_id,
                conversation_id=conversation_id,
                trace_id=trace_id,
            )
            sink = EventSink()
            from agentcore.runtime.recover_hooks import build_crash_delegate_tool

            delegate_tool = await build_crash_delegate_tool(lease, state, sink=sink)
            if delegate_tool is None:
                logger.warning(
                    "recover.lease_no_delegate",
                    message_id=message_id,
                )
                should_release = await salvage_interrupted_turn(
                    message_id=message_id,
                    conversation_id=conversation_id,
                    trace_id=trace_id if isinstance(trace_id, str) else None,
                    reason=TurnInterruptReason.REDRIVE_FAILED.value,
                )
                return None
            armed_eid = state.execution_id or new_id()
            eid = armed_eid
            await recover_turn(
                state=state,
                sink=sink,
                delegate_tool=delegate_tool,
                execution_id=armed_eid,
            )
            return armed_eid

        try:
            # Timeout only covers rebuild/arm — drive wait is outside this budget.
            armed_eid = await asyncio.wait_for(_arm_redrive(), timeout=timeout)
            if armed_eid is not None:
                await _await_crash_redrive_drive(armed_eid)
                logger.info("recover.lease_done", message_id=message_id)
                should_release = True
        except TimeoutError:
            _stop_background()
            should_release = await _salvage(
                reason=TurnInterruptReason.REDRIVE_FAILED.value,
                event="recover.lease_timeout",
            )
    except asyncio.CancelledError:
        # Strong-ref gap / process teardown used to cancel after ready with no salvage.
        logger.error(
            "recover.lease_cancelled",
            message_id=message_id,
            attempts=attempts,
        )
        _stop_background()
        with contextlib.suppress(Exception):
            should_release = await salvage_interrupted_turn(
                message_id=message_id,
                conversation_id=conversation_id,
                trace_id=trace_id if isinstance(trace_id, str) else None,
                reason=TurnInterruptReason.REDRIVE_FAILED.value,
            )
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(
            "recover.lease_failed",
            message_id=message_id,
            error=str(e),
            exc_info=True,
        )
        _stop_background()
        with contextlib.suppress(Exception):
            should_release = await salvage_interrupted_turn(
                message_id=message_id,
                conversation_id=conversation_id,
                trace_id=trace_id if isinstance(trace_id, str) else None,
                reason=TurnInterruptReason.REDRIVE_FAILED.value,
            )
    finally:
        if lease_stop is not None:
            lease_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        if should_release:
            await release_turn_lease(message_id)
        else:
            with contextlib.suppress(Exception):
                await orphan_turn_lease(message_id)
