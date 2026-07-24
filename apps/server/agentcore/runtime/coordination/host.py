"""Non-blocking coordinated WaveScheduler host (CEO 协调模式 Phase 2).

Starts the same drive machinery as blocking ``drive``, but returns immediately
after the team is armed; progress posts into :class:`CoordinationSession`.

Mid-coordination secondary ``delegate`` merges into the active session (same
collaboration graph / same event queue) — aligned with classic-path dynamic
delegation — rather than overwriting via :func:`set_active_coordination`.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from agentcore.core.logging import get_logger
from agentcore.core.types import ToolEffect
from agentcore.runtime.coordination.journal import record_coordination_snapshot
from agentcore.runtime.coordination.session import (
    MAX_DECISION_BUDGET,
    MAX_PROGRESS_BUDGET,
    CoordinationEvent,
    CoordinationEventKind,
    CoordinationSession,
    active_coordination,
    bind_host_journal,
    coordination_budget_for_batch,
    finish_detached_coordination,
    set_active_coordination,
    should_enter_coordination,
    split_coordination_budget,
)
from agentcore.runtime.delegate.team_synthesis import worker_output_blurb
from agentcore.tools.protocol import ToolResult

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunState

DelegateTool = Any

logger = get_logger(__name__)


def _bind_session_host_journal(session: CoordinationSession) -> None:
    """Pin the arming turn's journal writer onto the session (pillar A)."""
    from agentcore.runtime.journal.writer import current_journal_writer

    writer = current_journal_writer.get()
    if writer is None:
        return
    bind_host_journal(session, writer=writer, turn_id=getattr(writer, "turn_id", None))


def _seed_session_completed(
    session: CoordinationSession,
    seed_completed: dict[str, RunState] | None,
) -> None:
    """Pre-fill completed_run_ids from host/resume seeds so completed/total stays honest."""
    if not seed_completed:
        return
    from agentcore.runtime.runs.types import RunPhase

    terminal = {
        RunPhase.COMPLETED,
        RunPhase.FAILED,
        RunPhase.CANCELLED,
        RunPhase.SKIPPED,
    }
    for run_id, state in seed_completed.items():
        if state.phase in terminal:
            session.mark_worker_completed(run_id)


def _start_echo_counts(
    plan: RunPlan,
    seed_completed: dict[str, RunState] | None,
) -> tuple[int, int]:
    """Return (added_count, already_completed_count) for the start echo."""
    if not seed_completed:
        return len(plan.nodes), 0
    seeded_ids = set(seed_completed)
    added = sum(1 for n in plan.nodes if n.run_id not in seeded_ids)
    return added, len(seeded_ids)


def _coordination_start_echo(
    *,
    roster: str,
    added: int,
    total: int,
    completed: int,
    seeded: bool,
) -> str:
    if seeded:
        head = (
            f"【队员已追加·协调模式】已追加 {added} 名队员（{roster}）；"
            f"图共 {total} 名，其中 {completed} 名已完成。\n"
            "队员正在后台报到；完成态由图事件异步呈现，勿在本回合宣称全员已就位。"
        )
    else:
        head = (
            f"【团队已启动·协调模式】已派出 {added} 名队员（{roster}）；"
            f"图共 {total} 名，其中 {completed} 名已完成。\n"
            "调度在后台继续；完成态由图事件异步呈现。"
        )
    return (
        f"{head}\n"
        "你将收到团队事件（worker_completed / note / escalation / "
        "user_interjection / all_completed）。完成进度与各队员完成摘要由系统自动展示给用户；"
        "仅当形成新的中间结论、发现各路产出冲突或需要方向修正时用 update_synthesis 更新合成草稿，"
        "勿为播报进度而更新；无需处置时调 wait（或空响应，系统已豁免），"
        "不要写「静默等待中」之类的正文——那会原样显示给用户，"
        "也勿用 delegate 占位等待（同构再派会被拒绝）；"
        "老板中途插话：相关则图内处置，无关则 queue_user_message 转对话级排队；"
        "全部完成后做最终合成并收口。"
        "用户要立等结果的快任务请用 finalize 阻塞收口；"
        "单 worker / finalize / 嵌套 lead / 显式 coordinate=false 仍走阻塞等待。"
    )


def _drop_all_completed_events(session: CoordinationSession) -> int:
    """Remove premature ``ALL_COMPLETED`` events after workers are appended mid-flight."""
    dropped = 0
    kept_pending: list[CoordinationEvent] = []
    for ev in session._pending:
        if ev.kind is CoordinationEventKind.ALL_COMPLETED:
            dropped += 1
        else:
            kept_pending.append(ev)
    session._pending = kept_pending
    kept_queued: list[CoordinationEvent] = []
    while True:
        try:
            ev = session._queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if ev.kind is CoordinationEventKind.ALL_COMPLETED:
            dropped += 1
        else:
            kept_queued.append(ev)
    for ev in kept_queued:
        session._queue.put_nowait(ev)
    return dropped


def _has_all_completed_in_flight(session: CoordinationSession) -> bool:
    """True when ALL_COMPLETED is already queued / pending / injected."""
    if session.all_completed_injected:
        return True
    if any(e.kind is CoordinationEventKind.ALL_COMPLETED for e in session._pending):
        return True
    queued: list[CoordinationEvent] = []
    while True:
        try:
            queued.append(session._queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    has = any(e.kind is CoordinationEventKind.ALL_COMPLETED for e in queued)
    for ev in queued:
        session._queue.put_nowait(ev)
    return has


def _ensure_terminal_all_completed(
    session: CoordinationSession,
    *,
    output: str = "",
) -> bool:
    """Invariant guard: backfill ALL_COMPLETED only when drive leaked a terminal miss.

    Normal paths post inside ``drive`` (success / criteria-gap / partial-fail).
    Triggering this means a *new* early-return forgot the terminal post — keep the
    CEO unblocked, but warn so the leak is visible.
    """
    if _has_all_completed_in_flight(session):
        return False
    payload: dict[str, Any] = {
        "completed": len(session.completed_run_ids),
        "total": session.total_workers,
    }
    if output.strip():
        payload["output"] = output.strip()[:4000]
    session.post(
        CoordinationEvent(kind=CoordinationEventKind.ALL_COMPLETED, payload=payload)
    )
    logger.warning(
        "coordination.all_completed_backfill",
        execution_id=session.execution_id,
        completed=len(session.completed_run_ids),
        total=session.total_workers,
        has_output=bool(output.strip()),
        detail=(
            "竞态兜底：drive 终态未投递 ALL_COMPLETED，host 已回填。"
            "主保障是终态对账（附着注入/harvest）；请追查 drive 提前返回竞态。"
        ),
    )
    return True


def _merge_into_active_coordination(
    tool: DelegateTool,
    plan: RunPlan,
    session: CoordinationSession,
    *,
    execution_id: str,
    seed_completed: dict[str, RunState] | None,
    finalize: bool,
    seed_notes: list[dict[str, str]] | None,
    complexity_hint: str,
    call_idx: int,
    completion_criteria: Any,
    coordination: str,
) -> ToolResult:
    """Append ``plan`` workers onto the live session (budget / cancel / arbitration kept)."""
    from agentcore.runtime.coordination.append_guard import (
        append_overlap_reject_message,
        declare_plan_artifacts,
        find_append_overlaps,
    )
    from agentcore.runtime.coordination.isomorphic import (
        merge_all_skipped_reject_message,
        merge_partial_skip_message,
    )
    from agentcore.runtime.delegate.batch_shape import annotate_batch_meta
    from agentcore.runtime.delegate.plan_events import plan_event
    from agentcore.runtime.runs.plan import RunPlan, RunPlanError
    from agentcore.workspace.write_claims import file_ownership_v2_enabled

    live = session.live_plan
    drive_running = session.drive_task is not None and not session.drive_task.done()

    # Playbook/DAG still in flight: reject appends that overlap incomplete nodes
    # on role duty or file deliverable targets (GEO collision class). C3: file
    # side also consults session ownership (completed owners still hold). force=true
    # bypasses — same escape hatch as isomorphic re-delegation.
    force = getattr(tool, "_delegate_force", False) is True
    ownership = session.ensure_file_ownership() if file_ownership_v2_enabled() else None
    if not force:
        overlaps = find_append_overlaps(
            plan,
            live,
            completed_run_ids=session.completed_run_ids,
            ownership=ownership,
        )
        if overlaps:
            completed_k = len(session.completed_run_ids)
            msg = append_overlap_reject_message(
                overlaps,
                completed=completed_k,
                total=session.total_workers,
            )
            logger.info(
                "coordination.append_overlap_rejected",
                execution_id=execution_id,
                overlaps=len(overlaps),
                reasons=[o.reason for o in overlaps],
                completed=completed_k,
                total=session.total_workers,
                call=call_idx,
            )
            return annotate_batch_meta(
                ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=msg,
                    effect=ToolEffect.CONTINUE,
                    contract_failure=True,
                ),
                node_count=len(plan.nodes),
                has_deps=any(n.depends_on for n in plan.nodes),
            )

    if live is None and drive_running:
        # Infeasible: background drive owns an unknown plan — do not dual-drive.
        logger.error(
            "coordination.merge_infeasible_no_live_plan",
            execution_id=execution_id,
            total_workers=session.total_workers,
        )
        return annotate_batch_meta(
            ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=(
                    "协调会话缺少活计划指针，无法安全追加队员。"
                    "请等当前团队 all_completed 后再 delegate，或用 replan(add=…) 在波边界追加。"
                ),
            ),
            node_count=len(plan.nodes),
            has_deps=any(n.depends_on for n in plan.nodes),
        )
    skipped: list[tuple[Any, str]] = []
    if live is None:
        # No live drive: adopt this batch as the live graph and re-arm below.
        live = plan
        session.live_plan = live
        added_nodes = list(plan.nodes)
    else:
        added_nodes = []
        for node in plan.nodes:
            try:
                live.add(node)
            except RunPlanError as exc:
                reason = str(exc)
                logger.warning(
                    "coordination.merge_skip_node",
                    execution_id=execution_id,
                    run_id=node.run_id,
                    error=reason,
                )
                skipped.append((node, reason))
                continue
            added_nodes.append(node)

    if not added_nodes and live is plan:
        added_nodes = list(plan.nodes)

    # Entire batch bounced (e.g. every run_id already on the live graph) — do not
    # mutate budget / emit plan / echo success; CEO must see a structured reject.
    if skipped and not added_nodes:
        completed_k = len(session.completed_run_ids)
        msg = merge_all_skipped_reject_message(
            skipped,
            completed=completed_k,
            total=session.total_workers,
        )
        logger.info(
            "coordination.merge_all_skipped",
            execution_id=execution_id,
            skipped=len(skipped),
            total_workers=session.total_workers,
            call=call_idx,
        )
        return annotate_batch_meta(
            ToolResult(
                tool_call_id="",
                success=False,
                output="",
                error=msg,
                effect=ToolEffect.CONTINUE,
                # 全批跳过是可自纠的契约拒绝（换 id / 换任务）——勿进熔断。
                contract_failure=True,
            ),
            node_count=0,
            has_deps=False,
        )

    added_count = len(added_nodes)
    session.total_workers = len(live.nodes)
    # C3: reserve artifacts for newly admitted nodes (replaces/continue transfer).
    if file_ownership_v2_enabled() and added_nodes:
        from agentcore.runtime.runs.executor_context import _ancestors_by_id

        declare_plan_artifacts(
            live,
            session.ensure_file_ownership(),
            force=force,
            only_run_ids={n.run_id for n in added_nodes},
            ancestor_map=_ancestors_by_id(live),
        )
    # Budget merge（两池遥测）：派新批按 batch 规模补充两池计数额度，各自封顶。
    topup_progress, topup_decision = split_coordination_budget(
        coordination_budget_for_batch(max(1, added_count))
    )
    session.progress_budget_remaining = min(
        MAX_PROGRESS_BUDGET, session.progress_budget_remaining + topup_progress
    )
    session.decision_budget_remaining = min(
        MAX_DECISION_BUDGET, session.decision_budget_remaining + topup_decision
    )
    # Secondary delegate's suspect-dep advisories ride the next injection too.
    if plan.advisories:
        session.dep_advisories.extend(plan.advisories)
    # cancel_ids / pending_arbitrations / resolved_arbitrations / draft retained.

    tool._sink.emit(plan_event(tool, execution_id, live))
    record_coordination_snapshot(session)

    if drive_running:
        # WaveScheduler re-scans ``plan.nodes`` each cycle — appended workers join.
        logger.info(
            "delegate.coordinate_merged",
            execution_id=execution_id,
            added=added_count,
            total_workers=session.total_workers,
            budget_remaining=session.budget_remaining,
            drive="live",
            call=call_idx,
        )
    else:
        # First drive already exited (possibly posted ALL_COMPLETED). Drop that
        # premature terminal event and arm a drive for the newly appended nodes only.
        dropped = _drop_all_completed_events(session)
        session.all_completed_injected = False
        if not session.active:
            session.active = True
        added_plan = RunPlan(
            nodes=list(added_nodes),
            origin=getattr(live, "origin", None) or plan.origin,
        )
        task = asyncio.create_task(
            _background_drive(
                tool,
                added_plan,
                execution_id=execution_id,
                seed_completed=seed_completed,
                finalize=finalize,
                seed_notes=seed_notes,
                complexity_hint=complexity_hint,
                coordination=coordination,
                call_idx=call_idx,
                completion_criteria=completion_criteria,
                session=session,
            ),
            name=f"coord-drive-merge-{execution_id[:8]}",
        )
        session.drive_task = task
        logger.info(
            "delegate.coordinate_merged",
            execution_id=execution_id,
            added=added_count,
            total_workers=session.total_workers,
            budget_remaining=session.budget_remaining,
            drive="rearmed",
            dropped_all_completed=dropped,
            call=call_idx,
        )

    completed_k = len(session.completed_run_ids)
    if skipped:
        output = merge_partial_skip_message(
            added_nodes=added_nodes,
            skipped=skipped,
            total_workers=session.total_workers,
            completed=completed_k,
        )
    else:
        roles = [n.role or n.agent_name or n.run_id for n in added_nodes]
        roster = "、".join(roles) if roles else "（无新队员）"
        output = (
            f"【队员已追加·协调模式】已追加 {added_count} 名队员（{roster}）；"
            f"图共 {session.total_workers} 名，其中 {completed_k} 名已完成。"
            "仍属同一协作图 / 同一协调会话。\n"
            "队员正在后台报到；完成态由图事件异步呈现，勿宣称全员已就位。"
            "取消请求与仲裁态保留；你将继续收到团队事件，全部完成后做最终合成。"
        )
    return annotate_batch_meta(
        ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            effect=ToolEffect.CONTINUE,
        ),
        node_count=added_count,
        has_deps=any(n.depends_on for n in added_nodes),
    )


def try_start_coordination(
    tool: DelegateTool,
    plan: RunPlan,
    *,
    execution_id: str,
    seed_completed: dict[str, RunState] | None,
    finalize: bool,
    seed_notes: list[dict[str, str]] | None,
    complexity_hint: str,
    call_idx: int,
    completion_criteria: Any,
    coordinate: bool,
    coordination: str = "none",
    session: CoordinationSession | None = None,
) -> ToolResult | None:
    """If the coordinate gate passes, arm a background drive and return the start result.

    Returns ``None`` when the caller should fall through to blocking ``drive``.
    Pass an existing ``session`` on ask_user resume to preserve draft / budget.

    When an **active** coordination session already exists for ``execution_id``
    (CEO mid-flight secondary ``delegate``), merges workers into that session
    instead of creating a second background drive / overwriting the registry.
    """
    # Secondary delegate while coordinating: merge before the ≥2 gate so a solo
    # append still joins the live team (classic dynamic-delegation parity).
    # Ignore coordinate=false here — a blocking drive beside a live session would
    # dual-drive; opt-out is only meaningful for the *first* arm.
    if session is None:
        existing = active_coordination(execution_id)
        if existing is not None and existing.active and tool._depth == 0 and not finalize:
            existing.event_sink = getattr(tool, "_sink", None) or existing.event_sink
            return _merge_into_active_coordination(
                tool,
                plan,
                existing,
                execution_id=execution_id,
                seed_completed=seed_completed,
                finalize=finalize,
                seed_notes=seed_notes,
                complexity_hint=complexity_hint,
                call_idx=call_idx,
                completion_criteria=completion_criteria,
                coordination=coordination,
            )

    has_checkpoint = any(bool(n.checkpoint_after) for n in plan.nodes)
    checkpoint_enabled = bool(getattr(tool, "_checkpoint_enabled", False))
    if session is None and not should_enter_coordination(
        coordinate=coordinate,
        worker_count=len(plan.nodes),
        finalize=finalize,
        depth=tool._depth,
        has_checkpoint=has_checkpoint,
        checkpoint_enabled=checkpoint_enabled,
    ):
        if has_checkpoint and checkpoint_enabled:
            logger.info(
                "coordination.skipped",
                reason="checkpoint_after_in_batch",
                execution_id=execution_id,
                nodes=len(plan.nodes),
                checkpoint_nodes=sum(1 for n in plan.nodes if n.checkpoint_after),
            )
        return None

    fresh_session = False
    if session is None:
        init_progress, init_decision = split_coordination_budget(
            coordination_budget_for_batch(len(plan.nodes))
        )
        session = CoordinationSession(
            execution_id=execution_id,
            total_workers=len(plan.nodes),
            progress_budget_remaining=init_progress,
            decision_budget_remaining=init_decision,
            conversation_id=str(getattr(tool, "_conversation_id", None) or ""),
        )
        session.live_plan = plan
        session.event_sink = getattr(tool, "_sink", None)
        _seed_session_completed(session, seed_completed)
        _bind_session_host_journal(session)
        set_active_coordination(session)
        record_coordination_snapshot(session)
        fresh_session = True
    else:
        if session.live_plan is None:
            session.live_plan = plan
        if not session.conversation_id:
            session.conversation_id = str(
                getattr(tool, "_conversation_id", None) or ""
            )
        # Resume / re-arm: re-attach live sink (not snapshotted).
        session.event_sink = getattr(tool, "_sink", None) or session.event_sink
        _seed_session_completed(session, seed_completed)
        if session.host_journal_writer is None:
            _bind_session_host_journal(session)
        set_active_coordination(session)

    # C3: first arm rejects sibling artifact crosses then declares; resume keeps snapshot.
    from agentcore.workspace.write_claims import file_ownership_v2_enabled

    force = getattr(tool, "_delegate_force", False) is True
    if file_ownership_v2_enabled() and fresh_session:
        from agentcore.runtime.coordination.append_guard import (
            append_overlap_reject_message,
            declare_plan_artifacts,
            find_sibling_artifact_crosses,
        )

        if not force:
            sibling_hits = find_sibling_artifact_crosses(plan)
            if sibling_hits:
                from agentcore.runtime.coordination.session import (
                    clear_active_coordination,
                )
                from agentcore.runtime.delegate.batch_shape import annotate_batch_meta

                msg = append_overlap_reject_message(
                    sibling_hits,
                    completed=len(session.completed_run_ids),
                    total=session.total_workers,
                )
                logger.info(
                    "coordination.sibling_artifact_rejected",
                    execution_id=execution_id,
                    overlaps=len(sibling_hits),
                    call=call_idx,
                )
                session.close()
                clear_active_coordination(execution_id)
                return annotate_batch_meta(
                    ToolResult(
                        tool_call_id="",
                        success=False,
                        output="",
                        error=msg,
                        effect=ToolEffect.CONTINUE,
                        contract_failure=True,
                    ),
                    node_count=len(plan.nodes),
                    has_deps=any(n.depends_on for n in plan.nodes),
                )
        declare_plan_artifacts(plan, session.ensure_file_ownership(), force=force)
        record_coordination_snapshot(session)
    elif file_ownership_v2_enabled() and session.file_ownership is None:
        # Resume without ownership in snapshot (legacy frame) — backfill from live plan.
        from agentcore.runtime.coordination.append_guard import declare_plan_artifacts

        live = session.live_plan or plan
        declare_plan_artifacts(live, session.ensure_file_ownership(), force=force)
        record_coordination_snapshot(session)

    # 疑似缺依赖提示搭车协调注入通道：随首个团队事件简报一并呈现给 CEO，不新增独立唤醒。
    if plan.advisories:
        session.dep_advisories.extend(plan.advisories)

    task = asyncio.create_task(
        _background_drive(
            tool,
            plan,
            execution_id=execution_id,
            seed_completed=seed_completed,
            finalize=finalize,
            seed_notes=seed_notes,
            complexity_hint=complexity_hint,
            coordination=coordination,
            call_idx=call_idx,
            completion_criteria=completion_criteria,
            session=session,
        ),
        name=f"coord-drive-{execution_id[:8]}",
    )
    session.drive_task = task

    roles = [n.role or n.agent_name or n.run_id for n in plan.nodes]
    roster = "、".join(roles)
    added_count, completed_count = _start_echo_counts(plan, seed_completed)
    # Wording: only pre-filled terminal seeds (append / partial resume) use「已追加」;
    # empty seed dict (team_preview continue) still reads as fresh「团队已启动」.
    append_echo = completed_count > 0
    logger.info(
        "delegate.coordinate_started",
        execution_id=execution_id,
        nodes=len(plan.nodes),
        added=added_count,
        already_completed=completed_count,
        call=call_idx,
        resumed=seed_completed is not None,
    )
    from agentcore.runtime.delegate.batch_shape import annotate_batch_meta

    return annotate_batch_meta(
        ToolResult(
            tool_call_id="",
            success=True,
            output=_coordination_start_echo(
                roster=roster,
                added=added_count,
                total=len(plan.nodes),
                completed=completed_count,
                seeded=append_echo,
            ),
            effect=ToolEffect.CONTINUE,
        ),
        node_count=len(plan.nodes),
        has_deps=any(n.depends_on for n in plan.nodes),
    )


async def _background_drive(
    tool: DelegateTool,
    plan: RunPlan,
    *,
    execution_id: str,
    seed_completed: dict[str, RunState] | None,
    finalize: bool,
    seed_notes: list[dict[str, str]] | None,
    complexity_hint: str,
    call_idx: int,
    completion_criteria: Any,
    session: CoordinationSession,
    coordination: str = "none",
) -> None:
    """Run blocking drive semantics, posting coordination events along the way.

    Owns an independent LLM client so chat-turn teardown ``llm.close()`` cannot
    ReadError-kill in-flight workers (async team model).
    """
    from agentcore.llm.factory import spawn_independent_llm
    from agentcore.runtime.delegate.drive import drive_coordinated

    own_llm, owns_llm = spawn_independent_llm(tool._llm)
    prior_llm = tool._llm
    tool._llm = own_llm
    try:
        result = await drive_coordinated(
            tool,
            plan,
            execution_id=execution_id,
            seed_completed=seed_completed,
            finalize=finalize,
            seed_notes=seed_notes,
            complexity_hint=complexity_hint,
            coordination=coordination,
            call_idx=call_idx,
            completion_criteria=completion_criteria,
            session=session,
        )
        # Boundary / pause results surface as coordination events (CEO still alive).
        # drive 在 session 路径上故意保留 ``_pending_*``（见 drive.py），此处消费后清掉。
        if tool._pending_pause:
            tool._pending_pause = False
            session.post(
                CoordinationEvent(
                    kind=CoordinationEventKind.BOUNDARY_YIELD,
                    payload={"reason": "checkpoint", "brief": "计划在 checkpoint 暂停"},
                )
            )
        elif tool._pending_boundary is not None:
            reason, nodes = tool._pending_boundary
            tool._pending_boundary = None
            from agentcore.runtime.delegate.supervised import format_boundary_for_ceo

            # Prefer the brief drive already formatted (includes completed worker output);
            # fall back to a fresh format when drive returned empty.
            brief = (result.output if result is not None and result.output else "") or (
                format_boundary_for_ceo(tool, reason, plan, {}, nodes)
            )
            session.post(
                CoordinationEvent(
                    kind=CoordinationEventKind.BOUNDARY_YIELD,
                    payload={
                        "reason": reason.value,
                        "brief": brief[:2000],
                        "boundary_run_ids": [n.run_id for n in nodes],
                    },
                )
            )
        elif result is not None and result.success:
            # Invariant: drive should already have posted; backfill only on leak.
            _ensure_terminal_all_completed(
                session,
                output=(result.output if result is not None else "") or "",
            )
    except asyncio.CancelledError:
        logger.info("delegate.coordinate_cancelled", execution_id=execution_id)
        # Soft-stop (ask_user hang-frame): do NOT wake with ALL_COMPLETED — that
        # would seal a fake「全员完成」into the pause snapshot. Resume re-drives
        # unfinished workers from the journal seed.
        # Process kill / turn interrupt while host is still waiting: wake with
        # DRIVE_CANCELLED (not ALL_COMPLETED) so inject/wait never imply success.
        if not session.soft_stop:
            with contextlib.suppress(Exception):
                session.post(
                    CoordinationEvent(
                        kind=CoordinationEventKind.DRIVE_CANCELLED,
                        payload={
                            "completed": len(session.completed_run_ids),
                            "total": session.total_workers,
                            "error": "协调调度被取消（进程关闭或回合中断）。",
                        },
                    )
                )
        raise
    except Exception:  # noqa: BLE001 — never kill the CEO loop via background task
        logger.exception("delegate.coordinate_failed", execution_id=execution_id)
        session.post(
            CoordinationEvent(
                kind=CoordinationEventKind.ALL_COMPLETED,
                payload={
                    "completed": len(session.completed_run_ids),
                    "total": session.total_workers,
                    "error": "后台调度异常结束，请基于已有结果收口。",
                },
            )
        )
    finally:
        tool._llm = prior_llm
        if owns_llm:
            with contextlib.suppress(Exception):
                close = getattr(own_llm, "close", None)
                if close is not None:
                    await close()
        record_coordination_snapshot(session)
        # 跨回合同图追加：后台 drive 结束时排干宿主 journal 写缓冲。
        with contextlib.suppress(Exception):
            from agentcore.runtime.delegate.graph_append import (
                current_graph_append_redirect,
            )

            redir = current_graph_append_redirect.get()
            if redir is not None and redir.execution_id == execution_id:
                await redir.host_writer.flush()
        finish_detached_coordination(session)


def post_worker_progress(
    session: CoordinationSession,
    plan: RunPlan,
    completed: dict[str, RunState],
    *,
    sink: Any,
    execution_id: str,
    previously: set[str],
) -> set[str]:
    """Post coordination events for newly terminal workers (preview already emitted)."""
    from agentcore.runtime.coordination.bridge import post_completed_escalations
    from agentcore.runtime.runs.types import RunPhase

    newly = set(completed) - previously
    terminal: set[str] = set()
    for run_id in newly:
        state = completed[run_id]
        if state.phase not in (
            RunPhase.COMPLETED,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
            RunPhase.SKIPPED,
        ):
            continue
        terminal.add(run_id)
        node = plan.by_id(run_id)
        role = (node.role if node else None) or run_id
        session.mark_worker_completed(run_id)
        if state.phase is RunPhase.FAILED:
            session.failed_run_ids.add(run_id)
        session.post(
            CoordinationEvent(
                kind=CoordinationEventKind.WORKER_COMPLETED,
                payload={
                    "run_id": run_id,
                    "role": role,
                    "status": state.phase.value,
                    "summary": worker_output_blurb(state),
                },
            )
        )
    # Safety net: transcript-harvested escalations that missed the live on_escalate bridge.
    if terminal:
        post_completed_escalations(session, plan, completed, newly=terminal)
    return set(completed)
