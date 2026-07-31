"""Between-round coordination wait for the CEO ReAct loop (Phase 2)."""

from __future__ import annotations

import time

from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.coordination.inject import events_to_messages
from agentcore.runtime.coordination.journal import record_coordination_snapshot
from agentcore.runtime.coordination.session import (
    CoordinationEvent,
    CoordinationEventKind,
    CoordinationSession,
    active_coordination,
)

logger = get_logger(__name__)

# Base idle wait for the next team event when the CEO has nothing else to do.
_COORD_WAIT_TIMEOUT_S = 120.0
# Idle backoff cap: each consecutive「无新事件」idle timeout doubles the wait
# (``base * 2**idle_streak``) up to this ceiling, so a quiet team stops burning a
# full LLM patrol round every ~2 min. Real events reset the streak (see wait.py).
_COORD_WAIT_TIMEOUT_MAX_S = 600.0
# Frontend UX heartbeat while blocked in wait_events (≤15s per task constraint).
_WAIT_HEARTBEAT_S = 15.0
# Progress-event batching (事件合并唤醒): after the first wake, coalesce follow-up
# progress events (worker_completed / note) instead of waking per event. Wake when
# ≥``_MERGE_BATCH_MAX`` events pile up OR ``_MERGE_WINDOW_S`` elapsed since the last
# wake — whichever first. Necessary decision points (terminal / escalation / conflict
# / interjection / per-worker timeout / boundary) never merge; they wake immediately.
_MERGE_BATCH_MAX = 3
_MERGE_WINDOW_S = 60.0


def _drive_exhausted(session: CoordinationSession) -> bool:
    """True when the background drive cannot produce further team events."""
    if session.total_workers <= 0:
        return False
    if len(session.completed_run_ids) < session.total_workers:
        return False
    task = session.drive_task
    return task is None or task.done()


def _synthetic_all_completed(session: CoordinationSession) -> CoordinationEvent:
    return CoordinationEvent(
        kind=CoordinationEventKind.ALL_COMPLETED,
        payload={
            "completed": len(session.completed_run_ids),
            "total": session.total_workers,
            "reason": "team_done_shortcircuit",
        },
    )


def _emit_coordination_wait(session: CoordinationSession, *, waiting: bool) -> None:
    """Push ``coordination_wait`` to the live SSE sink (best-effort; never raises)."""
    sink = session.event_sink
    if sink is None:
        return
    try:
        from agentcore.runtime.events import coordination_wait

        sink.emit(
            coordination_wait(
                execution_id=session.execution_id,
                waiting=waiting,
                completed=len(session.completed_run_ids),
                total=session.total_workers,
            )
        )
    except Exception:  # noqa: BLE001 — UX signal must never break the CEO loop
        logger.warning(
            "coordination.wait_sse_failed",
            execution_id=session.execution_id,
            waiting=waiting,
            exc_info=True,
        )


async def _wait_events_with_ux(
    session: CoordinationSession,
    *,
    timeout: float,
) -> list[CoordinationEvent]:
    """``wait_events`` with enter/exit ``coordination_wait`` SSE + ≤15s heartbeats."""
    import asyncio

    _emit_coordination_wait(session, waiting=True)
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return []
            chunk = min(_WAIT_HEARTBEAT_S, remaining)
            events = await session.wait_events(timeout=chunk)
            if events:
                return events
            # Still blocked — refresh completed/total for the waiting UI.
            _emit_coordination_wait(session, waiting=True)
    finally:
        _emit_coordination_wait(session, waiting=False)


def _idle_wait_timeout(session: CoordinationSession) -> float:
    """Idle wait with exponential backoff (空转唤醒降频).

    First idle wait uses ``_COORD_WAIT_TIMEOUT_S``; each further「无新事件」idle
    timeout widens it by ``2**idle_streak`` up to ``_COORD_WAIT_TIMEOUT_MAX_S``, so a
    quiet team is patrolled ever less often (still patrolled — 保留卡死巡查语义).
    """
    timeout = _COORD_WAIT_TIMEOUT_S * (2 ** max(0, session.idle_streak))
    return min(timeout, _COORD_WAIT_TIMEOUT_MAX_S)


def _idle_patrol_nudge(session: CoordinationSession) -> CoordinationEvent:
    """Periodic「无事件」patrol nudge (distinct from a per-worker TIMEOUT).

    Kept so the CEO can still notice a wedged worker and ``cancel_worker`` — the
    frequency is throttled by :func:`_idle_wait_timeout`, not removed. When the
    team truly stalled (no in-flight LLM/tool), attach each worker's progress
    line so the CEO can decide without guessing.
    """
    progress = session.worker_progress_summary()
    reason = (
        f"等待团队事件超时（已完成 {len(session.completed_run_ids)}/"
        f"{session.total_workers}）。可继续静默等待、cancel_worker（队员"
        "疑似卡死时）、或 ask_user；期间无新语义增量勿调 update_synthesis。"
        f"\n{progress}"
    )
    return CoordinationEvent(
        kind=CoordinationEventKind.TIMEOUT,
        payload={
            "run_id": "",
            "role": "team",
            "status": "idle_wait",
            "reason": reason,
        },
    )


async def _accumulate_batch(
    session: CoordinationSession,
    events: list[CoordinationEvent],
) -> list[CoordinationEvent]:
    """Coalesce follow-up progress events into one wake (事件合并唤醒).

    Holds the initial (non-necessary) progress batch until ≥``_MERGE_BATCH_MAX``
    events accumulate OR ``_MERGE_WINDOW_S`` has elapsed since the last wake —
    whichever comes first. A necessary decision event arriving mid-hold breaks out
    immediately (终局 / 升级 / 冲突不拖延). Never held before the first wake
    (``seconds_since_wake() is None`` → the first completion is itself a decision
    point and must wake at once).
    """
    batch = list(events)
    while len(batch) < _MERGE_BATCH_MAX:
        if session.is_necessary_decision(batch):
            break
        since = session.seconds_since_wake()
        if since is None:
            break
        remaining = _MERGE_WINDOW_S - since
        if remaining <= 0:
            break
        more = await session.wait_events(timeout=remaining)
        if not more:
            break
        batch.extend(more)
    return batch


async def await_coordination_injection(
    messages: list[LLMMessage],
) -> list[LLMMessage]:
    """If a coordination session is active, wait for team events and inject them.

    Called at the top of each ReAct round after the first. Returns messages to
    append (possibly empty when not coordinating).

    唤醒降噪（协调层记账开销治理）：
    - 进展攒批（:func:`_accumulate_batch`）：非必要的 worker_completed / note 合并成一次
      唤醒（≥3 事件或距上次唤醒≥60s），而非每个完成都醒。
    - 空转退避（:func:`_idle_wait_timeout`）：无事件的 idle 巡查按 ``2**idle_streak`` 拉长
      等待，不再每~2 分钟烧一次全量 LLM 轮；仍保留卡死巡查（周期性 patrol nudge）。
    - 两池预算（进度池 / 决策池，见 session.py）：例行进展消耗【进度池】；必要决策
      （终局 / 升级 / 冲突 / 插话 / 单员超时 / 边界）消耗【决策池】但永不因预算被跳过。
      进度池耗尽 → 例行进展攒进 ``held``、不再唤醒 LLM，随下次必要唤醒（或空转巡查 / 终局）
      一并注入——信息不丢、不烧 LLM 轮；决策池专款专用，派批 / 仲裁 / 终稿始终有预算。
    """
    session = active_coordination()
    if session is None or not session.active:
        return []

    t0 = time.perf_counter()
    logger.info(
        "coordination.wait_start",
        execution_id=session.execution_id,
        completed=len(session.completed_run_ids),
        total=session.total_workers,
        progress_budget=session.progress_budget_remaining,
        decision_budget=session.decision_budget_remaining,
        drive_done=(
            session.drive_task is None or session.drive_task.done()
        ),
    )

    # 双池降级为纯遥测（批次 4）：不再因进度池耗尽 HOLD；合并窗口仍攒批，预算只计数。
    merged = 0
    wait_reason = "drained"
    while True:
        events = session.drain_nowait()
        wait_reason = "drained"
        if events:
            # Real team activity already queued — clear any idle-patrol backoff.
            session.reset_idle_backoff()
        elif _drive_exhausted(session):
            # 竞态兜底（非主保障）：主保障见终态对账（附着注入 / harvest）。
            wait_reason = "team_done_shortcircuit"
            events = [_synthetic_all_completed(session)]
            logger.warning(
                "coordination.team_done_shortcircuit",
                execution_id=session.execution_id,
                completed=len(session.completed_run_ids),
                total=session.total_workers,
                detail=(
                    "竞态兜底：全员已完成且 drive 已结束，队列仍无终态事件。"
                    "主保障是终态对账（附着注入/harvest）；请追查 drive/host 漏投竞态。"
                ),
            )
        else:
            events = await _wait_events_with_ux(
                session, timeout=_idle_wait_timeout(session)
            )
            if events:
                session.reset_idle_backoff()
                wait_reason = "waited"
            else:
                # No coordination events for the idle window. If workers still have
                # in-flight LLM/tool calls, progress simply has not posted yet —
                # do NOT fire a TIMEOUT patrol nudge (那会烧冤枉 LLM 轮). Instead:
                # one short re-wait for real events, then yield empty so the captain
                # can still act (ask_user / cancel_worker) while the team stays busy.
                # Infinite ``continue`` would park the CEO until workers finish and
                # break mid-wave soft-stop / 显式转后台.
                if session.has_inflight_work():
                    wait_reason = "idle_active"
                    logger.info(
                        "coordination.idle_patrol_deferred",
                        execution_id=session.execution_id,
                        completed=len(session.completed_run_ids),
                        total=session.total_workers,
                        busy=len(session._busy_workers),
                        running=len(session.running_workers()),
                    )
                    more = await _wait_events_with_ux(
                        session, timeout=min(1.0, _WAIT_HEARTBEAT_S)
                    )
                    if more:
                        events = more
                        session.reset_idle_backoff()
                        wait_reason = "waited"
                    else:
                        # wall + 0 完成：禁止 idle_yield（主回合先收摊 / turn_detached）。
                        # 可继续等真实团队事件；非 wall 或已有完成保持原 detach 语义。
                        if (
                            session.coordination == "wall"
                            and len(session.completed_run_ids) == 0
                        ):
                            logger.info(
                                "coordination.idle_yield_held_wall_zero",
                                execution_id=session.execution_id,
                                completed=0,
                                total=session.total_workers,
                                busy=len(session._busy_workers),
                            )
                            continue
                        logger.info(
                            "coordination.idle_yield_to_captain",
                            execution_id=session.execution_id,
                            completed=len(session.completed_run_ids),
                            total=session.total_workers,
                            busy=len(session._busy_workers),
                        )
                        # Same wake timing; inject pipeline progress so CEO does not
                        # read「闲着了」and append overlapping workers.
                        from agentcore.runtime.coordination.inject import (
                            idle_yield_messages,
                        )

                        return idle_yield_messages(session)
                else:
                    session.bump_idle_backoff()
                    wait_reason = "idle_timeout"

        # 攒批：仅对「真实到达且非必要」的进展事件合并唤醒；必要决策点与空转巡查不攒批。
        if (
            events
            and wait_reason in ("drained", "waited")
            and not session.is_necessary_decision(events)
        ):
            before = len(events)
            events = await _accumulate_batch(session, events)
            merged += len(events) - before

        nudge = False
        if not events:
            # Still coordinating but nothing arrived — patrol nudge (卡死巡查兜底).
            events = [_idle_patrol_nudge(session)]
            nudge = True

        necessary = session.is_necessary_decision(events)
        # 必要决策：记决策池遥测，立即唤醒。
        if necessary:
            session.consume_decision_budget()
            break
        # 空转巡查 nudge：保留卡死巡查语义，直接唤醒，不消耗任一池。
        if nudge:
            break
        # 例行进展：记进度池遥测并唤醒（池耗尽仍唤醒；合并窗口已在上方处理）。
        if not session.consume_progress_budget():
            logger.info(
                "coordination.progress_budget_floor",
                execution_id=session.execution_id,
                decision_budget=session.decision_budget_remaining,
            )
        break

    # 记账首个完成等决策点（对齐 is_necessary_decision）。
    session.note_decision_points(events)

    waited_ms = int((time.perf_counter() - t0) * 1000)
    event_kinds = [e.kind.value for e in events]
    logger.info(
        "coordination.wait_end",
        execution_id=session.execution_id,
        waited_ms=waited_ms,
        wait_reason=wait_reason,
        events=event_kinds,
        merged=merged,
        idle_streak=session.idle_streak,
        completed=len(session.completed_run_ids),
        total=session.total_workers,
        progress_budget=session.progress_budget_remaining,
        decision_budget=session.decision_budget_remaining,
    )

    has_terminal = any(
        e.kind
        in (
            CoordinationEventKind.ALL_COMPLETED,
            CoordinationEventKind.DRIVE_CANCELLED,
        )
        for e in events
    )
    if has_terminal:
        session.mark_settled("attached_inject")
    has_all = any(e.kind is CoordinationEventKind.ALL_COMPLETED for e in events)
    if has_all:
        session.all_completed_injected = True
        session.close()
        logger.info(
            "coordination.all_completed",
            execution_id=session.execution_id,
            completed=len(session.completed_run_ids),
            total=session.total_workers,
        )

    record_coordination_snapshot(session)
    injected = events_to_messages(session, events)
    # dep_advisories (builder.suspect_missing_dep 搭车) rode this injection via
    # ``format_coordination_events`` — consume once so later injections stay clean.
    if session.dep_advisories:
        session.dep_advisories.clear()
    # Stamp this wake so the next batch of progress events throttles against it.
    session.note_wake()
    logger.debug(
        "coordination.injected",
        execution_id=session.execution_id,
        events=event_kinds,
        progress_budget=session.progress_budget_remaining,
        decision_budget=session.decision_budget_remaining,
    )
    return injected
