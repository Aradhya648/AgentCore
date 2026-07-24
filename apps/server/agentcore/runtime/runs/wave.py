"""WaveScheduler — the concrete RunScheduler: continuous, dependency-driven execution.

The system's one scheduler. It owns *scheduling* control flow only —
ready-selection, the skip cascade, abort, the concurrency cap, per-node retry, and
accepting nodes appended mid-run — while *how* a node runs is the injected
:class:`RunExecutor`'s, and event emission / dependency-context assembly stay the
host's.

Dispatch is **continuous (event-driven)**, not wave-synchronous: a ready node is
launched the moment a slot frees, and a node becomes ready the moment *its own*
deps finish — it does NOT wait for the rest of its topological "wave". So a fast
node's dependents start while a slow *independent* sibling is still running, and a
freed concurrency slot is refilled immediately instead of idling until the whole
batch drains. (The legacy barrier scheduler held both back to the slowest node in
each wave — the latency this class exists to remove.)

Tree-wide concurrency stays bounded the same way (分而不乘): this scheduler runs at
most ``width`` nodes at once and hands each child a budget of ``budget // width``
(:func:`concurrency.child_budget`), so a node whose executor fans out into a nested
scheduler (阶段2) can't multiply past the configured parallel budget
(``settings.engine_max_parallel_delegations``, fallback ``MAX_PARALLEL_DELEGATIONS``). Because waves
now *overlap*, the divisor is the fixed ``width`` (not a per-wave chunk size) — that
keeps the sum of concurrent child budgets ≤ the parent budget without a tree-shared
lock (the recursive-semaphore deadlock the ContextVar budget exists to avoid).

Failure strategy per node is :attr:`RunPolicy.on_failure` (retry → re-run then
cascade-skip dependents; skip → cascade-skip dependents; abort → drain in-flight
then stop; degrade → dependents proceed). Cascade-skipped dependents revive when a
``replaces_run_id`` rewrite removes the failed edge (协调补派 / replan add).

→ 见设计: docs/03-AI核心/执行引擎架构设计.md §八（Run 模型）
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace

from agentcore.core.logging import get_logger
from agentcore.runtime.runs.concurrency import (
    child_budget,
    current_budget,
    resolve_max_parallel,
    set_budget,
)
from agentcore.runtime.runs.plan import RunPlan, RunPlanError
from agentcore.runtime.runs.scheduler import (
    BoundaryOutcome,
    BoundaryReason,
    OnBoundary,
    RunExecutor,
)
from agentcore.runtime.runs.types import (
    BatchMetrics,
    NodeTiming,
    RunPhase,
    RunSpec,
    RunState,
)

logger = get_logger(__name__)

# Host progress hook: sync (legacy tests) or async (drive hot-continue).
OnProgress = Callable[[Mapping[str, RunState]], None | Awaitable[None]]
# Optional per-node completion hook (additive): fires once when an executed node
# reaches a terminal RunState — before dependents are considered. Cascade-skipped
# nodes that never ran do NOT fire this (they only hit ``on_skipped``).
OnNodeDone = Callable[[str, RunState], None | Awaitable[None]]
# Host skip-materialisation hook: (run_id, agent_id, reason) where reason is
# ``cascade`` | ``abort``. Drive wires this to ``sink.emit(run_skipped(...))``.
OnSkipped = Callable[[str, str, str], None]


def _merge_retry_billing(prior: RunState, current: RunState) -> RunState:
    """Fold token/cost spend from earlier infra-retry attempts into the returned state.

    B-deep 失败计费 survives scheduler retries: a node that metered spend on attempt 1
    then fails again on attempt 2 must not drop attempt 1 from the final RunState the
    ledger and UI read.
    """
    if not prior.usage:
        return current
    merged_usage = dict(current.usage)
    for key, value in prior.usage.items():
        merged_usage[key] = merged_usage.get(key, 0) + value
    merged_cost = dict(current.cost)
    for key, value in prior.cost.items():
        # String annotations (currency / pricing_source / credential_source) are not
        # summable — keep current's value, fall back to prior's when absent.
        if isinstance(value, str):
            merged_cost.setdefault(key, value)
        else:
            existing = merged_cost.get(key, 0)
            if isinstance(existing, str):
                continue
            merged_cost[key] = int(existing) + int(value)
    return replace(current, usage=merged_usage, cost=merged_cost)


class WaveScheduler:
    """Concrete :class:`RunScheduler` — drives a :class:`RunPlan` to terminal with
    continuous, dependency-driven dispatch."""

    def __init__(self, max_parallel: int | None = None) -> None:
        # ``None`` → resolve the configured dispatch width lazily
        # (settings.engine_max_parallel_delegations, fallback MAX_PARALLEL_DELEGATIONS); an
        # explicit value (a consumer's own resolved knob) wins. A single scheduler's width
        # shares the SAME knob as the tree-wide budget so neither alone re-bottlenecks a
        # wide fan-out.
        resolved = max_parallel if max_parallel is not None else resolve_max_parallel()
        self._max_parallel = max(1, resolved)

    async def run(
        self,
        plan: RunPlan,
        executor: RunExecutor,
        *,
        seed_completed: Mapping[str, RunState] | None = None,
        should_stop: Callable[[], bool] | None = None,
        priority_reserve_hit: Callable[[], bool] | None = None,
        cancel_run_ids: Callable[[], frozenset[str]] | None = None,
        on_progress: OnProgress | None = None,
        on_node_done: OnNodeDone | None = None,
        on_boundary: OnBoundary | None = None,
        on_skipped: OnSkipped | None = None,
        metrics_sink: list[BatchMetrics] | None = None,
    ) -> dict[str, RunState]:
        """Drive ``plan`` to completion; return each node's terminal
        :class:`RunState` by ``run_id`` (cascade-skipped nodes included).

        A node is dispatched as soon as (a) all its ``depends_on`` are terminal and
        (b) a concurrency slot is free; the loop then waits for the *next* node to
        finish and immediately re-evaluates — so dependents start the moment their
        own deps land and a freed slot is refilled right away. ``plan.nodes`` is
        re-scanned each cycle, so a node appended mid-run (``RunPlan.add``) joins as
        soon as it is eligible.

        Entry runs a cheap ``plan.waves()`` topology self-check (same as build-time):
        a cycle or dangling ``depends_on`` raises :class:`RunPlanError` instead of
        silently dropping unreachable nodes from the result map.

        - ``seed_completed`` pre-seeds finished nodes (a resume): they are treated as
          done, so only the unfinished tail re-runs.
        - ``should_stop`` is checked before each dispatch decision; once True no new
          node is launched, in-flight nodes are drained, and the partial map is
          returned (a soft pause — the un-run tail is left out so a resume re-runs
          it). An in-flight node is never interrupted by it.
        - ``priority_reserve_hit`` (turn delivery reserve): when True and a pending
          ``ceiling_priority`` node remains, ready non-priority nodes are soft-skipped
          immediately (materialised SKIPPED into the completed map) so lenient fan-in
          can admit the priority tail; priority nodes still dispatch. No-op when no
          pending priority node exists. Orthogonal to hard ``should_stop``.
        - ``cancel_run_ids`` is polled each cycle; run_ids in the returned set that
          are currently in-flight are cancelled individually — the cancelled node gets
          ``RunPhase.CANCELLED``, siblings keep running, and dependents follow
          the fan-in rule: default ≥1 upstream COMPLETED → still run (absent
          upstreams annotated in task input); ``require_upstream=True`` keeps
          cascade-skip on any cancel/failure. ``force_continue=True`` allows a
          node even with zero successful upstreams. A dependent revived via
          ``replaces_run_id`` still runs.
          Used by delegate drive for user-initiated worker redirect and hard-timeout
          force-cancel.
        - ``on_progress`` fires after *each* node finishes with the completed-so-far
          map, so the host gets smooth progress (one increment per node).
        - ``on_node_done`` (optional, additive) fires once per *executed* node with
          ``(run_id, state)`` at the same moment — hosts that only care about the
          just-finished node (e.g. debate pretrial per-investigator persist) can
          avoid diffing the completed map. Cascade-skipped / never-ran nodes do not
          fire it.
        - ``on_boundary`` (受监督的波循环) is the host's decision-boundary hook, fired
          once in-flight work has *drained to a quiescent point* (draining first keeps
          the persisted snapshot consistent so a resume re-runs exactly the un-run
          tail). It is awaited with the :class:`BoundaryReason`, the triggering
          node(s), and the completed map, and returns a :class:`BoundaryOutcome`:
          ``PROCEED`` keeps scheduling, ``ABORT`` ends it like a graceful abort
          (un-run tail materialised SKIPPED), ``YIELD`` soft-pauses like
          ``should_stop`` (partial map, un-run tail LEFT OUT for a resume). Three
          reasons fire it:
          • ``CHECKPOINT`` (结构化挂起 2a) — a ``checkpoint_after`` node COMPLETED while
            downstream remains (the user plan_review). A *failed* checkpoint node does
            not pause — its ``on_failure`` governs the cascade.
          • ``BIND`` (晚绑定) — a ``bind_after_deps`` node's deps are all resolved but it
            is not yet finalised; it is never dispatched unbound, so it resolves only
            here (the CEO ``replan`` hand-back).
          • ``SCOPE`` (偏离信号 / 自底向上反应臂) — a COMPLETED node flagged a 职责/范围
            deviation (``escalate kind=scope``) while not-yet-run downstream remains; the
            CEO re-steers the un-run tail. Fires once per signal (surfacing marks it
            consumed), no live user needed (the reactive twin of ``BIND``).
          No hook ⇒ all markers inert (a ``bind_after_deps`` node then dispatches
          normally; a scope escalation just rides to synthesis); no marked node / no
          pending ⇒ untouched.
        - ``on_skipped`` fires once per newly materialised SKIPPED node at wave close
          (cascade-skip set + graceful-abort tail), with ``reason`` ``cascade`` or
          ``abort``. Drive wires it to ``run_skipped`` SSE so the graph shows「未执行」
          instead of forever-pending. Seeded SKIPPED nodes are not re-emitted.
        - ``metrics_sink`` (调度埋点量化), when given, receives ONE :class:`BatchMetrics`
          appended at terminal — concurrency / parallelism / slot-starvation / outcome
          counts for this run — for the host to log. Kept as a sink (not a return /
          logging call) so the scheduler stays host-agnostic. Not appended on a cancel
          (the ``except`` re-raises first); a soft ``should_stop`` pause still records it.

        On external cancel (user stop) every in-flight child is cancelled and
        awaited before the cancellation propagates — a worker task is never orphaned.
        """
        completed: dict[str, RunState] = dict(seed_completed or {})
        skipped: set[str] = set()
        # Every run_id that has been launched (running, finished, or pre-seeded) so a
        # node is never dispatched twice across the continuous re-scan.
        dispatched: set[str] = set(completed)
        running: dict[asyncio.Task[RunState], str] = {}
        # checkpoint_after nodes that COMPLETED and whose plan_review hasn't fired.
        checkpoint_pending: list[RunSpec] = []
        aborted = False
        stopped = False

        # Cheap topology self-check (defense): build-time paths already call
        # ``plan.waves()``; catch plans that bypassed construction (direct construct /
        # bad resume seed). Fail explicitly — never silently drop cycle / dangling nodes.
        try:
            plan.waves()
        except RunPlanError as exc:
            logger.warning("wave.bad_topology", error=str(exc), nodes=len(plan.nodes))
            raise

        # Concurrency width + per-child budget. Recalculated when the live plan grows
        # (coordinate merge / secondary delegate) so newly appended nodes raise the
        # cap up to global max_parallel and the tree budget — not frozen at entry.
        def _recompute_width() -> tuple[int, int]:
            n_pending = sum(1 for n in plan.nodes if n.run_id not in completed)
            w = min(self._max_parallel, current_budget(), max(1, n_pending))
            return w, child_budget(w)

        width, per_child_budget = _recompute_width()
        last_plan_size = len(plan.nodes)

        # 晚绑定 (受监督的波循环): defer ``bind_after_deps`` nodes to the bind boundary
        # ONLY when a host hook can resolve them; with no hook the marker is inert and
        # such a node dispatches normally (parity with ``checkpoint_after``-without-hook).
        defer_bind = on_boundary is not None

        # 调度埋点量化 (orthogonal to scheduling — see BatchMetrics): wall start, per-node
        # dispatch times (→ busy_ms occupancy), the concurrency high-water mark, how many
        # nodes this run launched, and slot-starvation cycles (ready nodes blocked by width).
        seeded_ids = set(completed)
        wall_start = time.monotonic()
        started_at: dict[str, float] = {}
        busy_ms = 0
        peak_running = 0
        dispatched_count = 0
        slot_starved = 0
        # Contiguous starvation episode latch: True while ready nodes are blocked by
        # width. Cleared when a slot frees or no ready nodes remain — so 50ms cancel
        # polls do not inflate the counter.
        slot_starved_latched = False
        # 多任务并行图 (并行时间线): each dispatched node's occupancy window as ms offsets from
        # wall_start — the same per-node dispatch/finish marks that feed busy_ms, kept (not
        # discarded) so the host can render real temporal parallelism. Dispatched nodes only.
        timeline: list[NodeTiming] = []
        # 受监督波循环埋点 (BatchMetrics §7.2): decision-boundary YIELDs fired this run, by
        # reason —晚绑定触发数 / 计划漂移返工触发数 / checkpoint. Counts fires (on_boundary
        # invocations), so a marked plan driven without a hook tallies zero.
        bind_boundaries = 0
        scope_boundaries = 0
        checkpoint_boundaries = 0
        cancelled_by_redirect: set[str] = set()

        try:
            while True:
                # Freeze dispatch while aborting, soft-stopping, or holding a completed
                # checkpoint node whose review hasn't fired (we must quiesce in-flight
                # work before the pause so a 2b resume re-runs only the un-run tail).
                holding = aborted or stopped or bool(checkpoint_pending)
                if not holding and should_stop is not None and should_stop():
                    stopped = True  # soft pause: stop launching, drain in-flight
                    holding = True
                # 晚绑定边界 (受监督的波循环): a ``bind_after_deps`` node whose deps are all
                # resolved is NOT dispatchable — its spec must first be finalised by the
                # host (CEO ``replan``). Once in-flight work is quiescent, yield the
                # boundary: PROCEED (host bound it in place → next ready-scan dispatches
                # it; if PROCEED left ``bind_after_deps`` set, treat as no-progress —
                # warn once and SKIP those nodes so the boundary cannot busy-wait),
                # YIELD (soft pause → CEO takes over, a resume re-runs the tail),
                # or ABORT. Inert unless a hook is wired AND such a node exists (none in an
                # ordinary plan), so a plan without late-binding is byte-for-byte untouched.
                if not holding and defer_bind and not running:
                    bind_ready = self._bind_pending(plan, completed, skipped, dispatched)
                    if bind_ready:
                        bind_boundaries += 1
                        outcome = await on_boundary(BoundaryReason.BIND, bind_ready, completed)
                        if outcome is BoundaryOutcome.ABORT:
                            aborted = True
                            holding = True
                        elif outcome is BoundaryOutcome.YIELD:
                            stopped = True
                            holding = True
                        elif outcome is BoundaryOutcome.PROCEED:
                            # Defense: host returned PROCEED but left bind_after_deps set
                            # → no progress. Do not re-fire (would busy-wait / livelock).
                            stuck = [n for n in bind_ready if n.bind_after_deps]
                            if stuck:
                                stuck_ids = [n.run_id for n in stuck]
                                logger.warning(
                                    "wave.bind_proceed_no_progress",
                                    run_ids=stuck_ids,
                                )
                                for n in stuck:
                                    skipped.add(n.run_id)
                                    dispatched.add(n.run_id)
                if not holding:
                    # Live-plan growth (coordinate merge): recalc width / child budget.
                    if len(plan.nodes) != last_plan_size:
                        width, per_child_budget = _recompute_width()
                        last_plan_size = len(plan.nodes)
                        logger.info(
                            "wave.width_recomputed",
                            width=width,
                            nodes=len(plan.nodes),
                            pending=sum(
                                1 for n in plan.nodes if n.run_id not in completed
                            ),
                        )
                    # ``replaces_run_id`` mid-run may rewrite edges off a failed dep —
                    # revive cascade-skipped dependents so they wait on the replacement.
                    self._revive_cascade_skips(plan, completed, skipped, dispatched)
                    ready_batch = list(
                        self._select_ready(
                            plan, completed, skipped, dispatched, defer_bind=defer_bind
                        )
                    )
                    # Turn delivery reserve: cut secondary ready nodes so priority
                    # (QA) can still admit under remaining headroom — only once the
                    # priority node already has ≥1 COMPLETED upstream (else cutting
                    # every section would leave zero successes and cascade-skip QA).
                    if (
                        priority_reserve_hit is not None
                        and priority_reserve_hit()
                        and self._priority_reserve_may_cut(
                            plan, completed, skipped, dispatched
                        )
                    ):
                        kept: list[RunSpec] = []
                        cut_any = False
                        for spec in ready_batch:
                            if bool(getattr(spec, "ceiling_priority", False)):
                                kept.append(spec)
                                continue
                            skipped.add(spec.run_id)
                            dispatched.add(spec.run_id)
                            if spec.run_id not in completed:
                                from agentcore.runtime.turn_token_budget import (
                                    REASON_TURN_TOKEN_BUDGET,
                                    TURN_TOKEN_RESERVE_SKIP_WARNING,
                                )

                                completed[spec.run_id] = RunState(
                                    phase=RunPhase.SKIPPED,
                                    warnings=[TURN_TOKEN_RESERVE_SKIP_WARNING],
                                    delivery_gaps=[
                                        {
                                            "description": TURN_TOKEN_RESERVE_SKIP_WARNING,
                                            "reason": REASON_TURN_TOKEN_BUDGET,
                                        }
                                    ],
                                )
                                if on_skipped is not None:
                                    agent_id = (
                                        (spec.agent_id if spec.agent_id else "")
                                        or spec.run_id
                                    )
                                    on_skipped(
                                        spec.run_id,
                                        agent_id,
                                        REASON_TURN_TOKEN_BUDGET,
                                    )
                                cut_any = True
                        # Soft-skips resolve deps — re-scan so priority may admit now.
                        if cut_any:
                            ready_batch = [
                                s
                                for s in self._select_ready(
                                    plan,
                                    completed,
                                    skipped,
                                    dispatched,
                                    defer_bind=defer_bind,
                                )
                                if bool(getattr(s, "ceiling_priority", False))
                            ]
                        else:
                            ready_batch = kept
                    dispatched_this_cycle = 0
                    for spec in ready_batch:
                        if len(running) >= width:
                            # One contiguous starvation episode (not per 50ms poll).
                            if not slot_starved_latched:
                                slot_starved += 1
                                slot_starved_latched = True
                            break
                        # Snapshot the completed map per dispatch: the executor reads
                        # its deps + iterates peer products from it, and ``completed``
                        # is mutated as concurrent nodes finish — a live view would
                        # risk "dict changed size during iteration".
                        snapshot = dict(completed)
                        task = asyncio.create_task(
                            self._run_node(spec, executor, snapshot, per_child_budget)
                        )
                        running[task] = spec.run_id
                        dispatched.add(spec.run_id)
                        started_at[spec.run_id] = time.monotonic()
                        dispatched_count += 1
                        dispatched_this_cycle += 1
                    if dispatched_this_cycle > 0 or not ready_batch:
                        slot_starved_latched = False
                    peak_running = max(peak_running, len(running))

                if not running:
                    break  # nothing in flight and (holding, or no node is ready) ⇒ done

                # Per-run user cancel (Phase 2a redirect): cancel specific in-flight tasks
                # without aborting the whole batch. Checked each cycle; a cancelled task
                # resolves on the next wait and is recorded as CANCELLED (not re-raised).
                if cancel_run_ids is not None and running:
                    for target_id in cancel_run_ids():
                        for task, rid in list(running.items()):
                            if rid == target_id and rid not in cancelled_by_redirect:
                                # msg="redirect" so executor_agent salvages + returns CANCELLED
                                # instead of re-raising (整轮 stop uses bare cancel).
                                task.cancel("redirect")
                                cancelled_by_redirect.add(rid)

                done, _ = await asyncio.wait(
                    set(running),
                    timeout=0.05 if cancel_run_ids is not None else None,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    continue
                for task in done:
                    run_id = running.pop(task)
                    if run_id in cancelled_by_redirect:
                        # User-initiated single cancel: absorb gracefully, don't propagate.
                        # Prefer the executor's salvaged CANCELLED RunState (partial transcript);
                        # fall back to empty CANCELLED if the task raised / never returned.
                        if not task.done():
                            task.cancel("redirect")
                        state: RunState | None = None
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            result = task.result()
                            if isinstance(result, RunState):
                                state = result
                        if state is None:
                            state = RunState(phase=RunPhase.CANCELLED)
                    elif task.cancelled():
                        raise asyncio.CancelledError  # external cancel, propagate
                    else:
                        state = task.result()
                    completed[run_id] = state
                    started = started_at.pop(run_id, None)
                    if started is not None:  # node occupancy: dispatch → finish
                        finished = time.monotonic()
                        busy_ms += int((finished - started) * 1000)
                        timeline.append(
                            NodeTiming(
                                run_id=run_id,
                                start_ms=int((started - wall_start) * 1000),
                                end_ms=int((finished - wall_start) * 1000),
                                outcome=state.phase.value,
                            )
                        )
                    if on_node_done is not None:
                        maybe_done = on_node_done(run_id, state)
                        if inspect.isawaitable(maybe_done):
                            await maybe_done
                    if on_progress is not None:
                        maybe = on_progress(completed)
                        if inspect.isawaitable(maybe):
                            await maybe
                    if state.phase is RunPhase.FAILED:
                        spec = plan.by_id(run_id)
                        on_failure = spec.policy.on_failure if spec else "degrade"
                        if on_failure == "abort":
                            aborted = True
                        elif on_failure in ("skip", "retry"):
                            # Default retry (and explicit skip): do not let dependents
                            # consume a failed/contract-miss product. Explicit degrade
                            # keeps the old best-effort path.
                            self._propagate_skip(plan, run_id, skipped, dispatched)
                    elif state.phase is RunPhase.CANCELLED:
                        # Cancel fan-in: strict ``require_upstream`` dependents
                        # cascade-skip immediately; lenient dependents wait for
                        # remaining upstreams (≥1 COMPLETED → still run).
                        self._propagate_cancel_skip(plan, run_id, skipped, dispatched)
                    elif state.phase is RunPhase.COMPLETED and on_boundary is not None:
                        # Track for the plan_review pause only when a hook is wired;
                        # without one the marker is fully inert (it must never freeze
                        # dispatch of the downstream it would have gated).
                        spec = plan.by_id(run_id)
                        if spec is not None and spec.checkpoint_after:
                            checkpoint_pending.append(spec)

                # 结构化挂起 2a (CHECKPOINT boundary): fire the plan_review only once
                # in-flight work has fully drained (quiescent) — so the snapshot the host
                # persists is consistent — and only while downstream work remains to gate.
                if on_boundary is not None and checkpoint_pending and not running:
                    nodes = checkpoint_pending
                    checkpoint_pending = []
                    pending_remains = any(
                        n.run_id not in completed and n.run_id not in skipped for n in plan.nodes
                    )
                    if pending_remains:
                        checkpoint_boundaries += 1
                        outcome = await on_boundary(BoundaryReason.CHECKPOINT, nodes, completed)
                        if outcome is BoundaryOutcome.ABORT:
                            aborted = True
                        elif outcome is BoundaryOutcome.YIELD:
                            stopped = True

                # 反应臂边界 (受监督的波循环 SCOPE arm / 自底向上反应臂): a COMPLETED node
                # flagged a 职责/范围 deviation (escalate kind=scope) OR a 依赖缺口·卡在缺输入
                # (escalate kind=dep, §2.4 变·worker 的「拉」). Once in-flight work has drained
                # (quiescent) and not-yet-run downstream remains, yield to the CEO/lead — it reads
                # the signal + the node's output and re-steers (scope) / replan(add)s a producer
                # (dep) for the un-run tail. Each signal fires ONCE: surfacing it marks it consumed,
                # so a PROCEED can't spin and a YIELD's resume (which re-seeds the same completed
                # nodes) won't re-fire. Inert unless a hook is wired AND a scope/dep escalation
                # surfaced — an ordinary plan never enters here (零新增回合).
                if on_boundary is not None and not running and not aborted and not stopped:
                    scope_nodes = self._scope_pending(plan, completed)
                    if scope_nodes and any(
                        n.run_id not in completed and n.run_id not in skipped for n in plan.nodes
                    ):
                        scope_boundaries += 1
                        outcome = await on_boundary(BoundaryReason.SCOPE, scope_nodes, completed)
                        for node in scope_nodes:
                            state = completed.get(node.run_id)
                            if state is not None:
                                for e in state.escalations:
                                    if e.get("kind") in ("scope", "dep"):
                                        e["consumed"] = True
                        if outcome is BoundaryOutcome.ABORT:
                            aborted = True
                        elif outcome is BoundaryOutcome.YIELD:
                            stopped = True
        except BaseException:
            # External cancel (user stop via task.cancel) or an unexpected crash:
            # cancel every in-flight child and let it unwind (subprocess kill,
            # run_cancelled(reason=stop)) before propagating, so no worker is orphaned
            # and journal/SSE always see the stop cancel. ``cancel("stop")`` matches
            # executor_agent's dual-reason contract (redirect vs stop); ``shield`` is
            # required because this except often runs under an already-cancelled wave
            # task — a bare await would be interrupted before children emit.
            for task in running:
                task.cancel("stop")
            if running:
                await asyncio.shield(asyncio.gather(*running, return_exceptions=True))
            raise

        # Materialise cascade-skipped nodes (never ran) as SKIPPED + emit run_skipped
        # so the graph shows「未执行」instead of forever-pending. Seeded entries are
        # left alone (setdefault / membership check) — no re-emit on resume.
        def _materialise_skipped(run_id: str, reason: str) -> None:
            if run_id in completed:
                return
            completed[run_id] = RunState(phase=RunPhase.SKIPPED)
            if on_skipped is None:
                return
            node = plan.by_id(run_id)
            agent_id = (node.agent_id if node and node.agent_id else "") or run_id
            on_skipped(run_id, agent_id, reason)

        for run_id in skipped:
            _materialise_skipped(run_id, "cascade")
        # A graceful abort (on_failure=abort, or a plan_review stop) ends scheduling
        # with an un-run tail; materialise it as SKIPPED — the same shape as a cascade
        # skip — so the CEO overview / graph shows「未执行」cleanly instead of a silently
        # absent node. (A soft should_stop pause is the resume substrate, not an abort,
        # so its tail is left out of ``completed`` to re-run on resume.)
        if aborted:
            for node in plan.nodes:
                _materialise_skipped(node.run_id, "abort")

        # 调度埋点量化: hand the host one snapshot of this run (counts exclude resume-seeded
        # nodes — they didn't run here). Appended only when a sink was given.
        if metrics_sink is not None:
            ran = [s for rid, s in completed.items() if rid not in seeded_ids]
            # escalate 信号占比 (raw → host derives scope/total): count over the nodes that
            # ran here, mirroring the outcome counts (seeded nodes' escalations belong to the
            # run that produced them, not this resumed slice).
            escalations = sum(len(s.escalations) for s in ran)
            scope_escalations = sum(
                1 for s in ran for e in s.escalations if e.get("kind") == "scope"
            )
            metrics_sink.append(
                BatchMetrics(
                    nodes=dispatched_count,
                    width=width,
                    peak_running=peak_running,
                    wall_ms=int((time.monotonic() - wall_start) * 1000),
                    busy_ms=busy_ms,
                    slot_starved=slot_starved,
                    completed=sum(1 for s in ran if s.phase is RunPhase.COMPLETED),
                    failed=sum(1 for s in ran if s.phase is RunPhase.FAILED),
                    skipped=sum(1 for s in ran if s.phase is RunPhase.SKIPPED),
                    cancelled=sum(1 for s in ran if s.phase is RunPhase.CANCELLED),
                    bind_boundaries=bind_boundaries,
                    scope_boundaries=scope_boundaries,
                    checkpoint_boundaries=checkpoint_boundaries,
                    escalations=escalations,
                    scope_escalations=scope_escalations,
                    timeline=timeline,
                )
            )
        return completed

    async def _run_node(
        self,
        spec: RunSpec,
        executor: RunExecutor,
        completed: Mapping[str, RunState],
        budget: int,
    ) -> RunState:
        """Run one node (with its retry policy) inside its own task context.

        Installs this child's reduced tree budget on the task-local context (no reset
        — the task's context copy is discarded when it ends) so a nested scheduler the
        executor may spawn divides from here, not from the root. ``retry`` re-runs up
        to ``max_retries`` (hard-capped at 3) with exponential backoff, returning the
        first completed state or the last failed one; any other policy runs exactly
        once. An executor crash is captured as a ``FAILED`` state (parity with the
        legacy ``gather(return_exceptions=True)``); a cancellation re-raises so the
        run-level cleanup can cancel siblings.
        """
        set_budget(budget)
        policy = spec.policy
        attempts = 1 + max(0, min(policy.max_retries, 3))
        last: RunState | None = None
        try:
            for attempt in range(attempts):
                if attempt > 0:
                    delay = policy.retry_delay_ms / 1000 * (2 ** (attempt - 1))
                    if delay > 0:
                        await asyncio.sleep(delay)
                    from agentcore.runtime.audit.hooks import on_run_retry

                    on_run_retry(
                        run_id=spec.run_id,
                        attempt=attempt,
                        source="on_failure",
                        error=str(last.error) if last and last.error else None,
                    )
                state = await executor(spec, completed)
                state.attempt = attempt
                if last is not None:
                    state = _merge_retry_billing(last, state)
                if state.phase is RunPhase.COMPLETED:
                    return state
                # Redirect salvage returns CANCELLED — never infra-retry a user cancel.
                if state.phase is RunPhase.CANCELLED:
                    return state
                last = state
                if policy.on_failure != "retry":
                    break
                # 确定性失败区分 (BL-6): a FAILED run flagged non-retryable (prompt 超长 /
                # 鉴权 / 余额 — an AgentCoreError.retryable=False threaded onto the state)
                # will re-fail identically, so stop burning ``max_retries`` + tokens on a
                # known-futile re-run. Record it (后端补记) so the deterministic acceptance
                # is visible in the delegated-turn audit trail instead of silent.
                if state.phase is RunPhase.FAILED and not state.error_retryable:
                    from agentcore.runtime.audit.hooks import on_run_deterministic_failure

                    on_run_deterministic_failure(
                        run_id=spec.run_id,
                        error=str(state.error) if state.error else None,
                    )
                    break
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 — an executor crash becomes FAILED
            return RunState(phase=RunPhase.FAILED, error=str(exc))
        return last or RunState(phase=RunPhase.FAILED)

    @staticmethod
    def _has_pending_ceiling_priority(
        plan: RunPlan,
        completed: Mapping[str, RunState],
        skipped: set[str],
        dispatched: set[str],
    ) -> bool:
        """True when some ``ceiling_priority`` node has not yet finished or been skipped."""
        for node in plan.nodes:
            if not bool(getattr(node, "ceiling_priority", False)):
                continue
            if node.run_id in completed or node.run_id in skipped:
                continue
            return True
        return False

    @staticmethod
    def _priority_reserve_may_cut(
        plan: RunPlan,
        completed: Mapping[str, RunState],
        skipped: set[str],
        dispatched: set[str],
    ) -> bool:
        """Whether reserve soft-skip of non-priority is safe for pending priority tails.

        Requires a pending ``ceiling_priority`` node that already has ≥1 COMPLETED
        upstream (lenient fan-in can still admit it after peers are cut). If every
        priority node still has zero successes, keep admitting sections normally.
        """
        for node in plan.nodes:
            if not bool(getattr(node, "ceiling_priority", False)):
                continue
            if node.run_id in completed or node.run_id in skipped:
                continue
            if node.run_id in dispatched:
                return True  # priority already in flight — still protect it
            successes = WaveScheduler._upstream_success_count(node, completed)
            if successes >= 1:
                return True
        return False

    def _select_ready(
        self,
        plan: RunPlan,
        completed: Mapping[str, RunState],
        skipped: set[str],
        dispatched: set[str],
        *,
        defer_bind: bool = False,
    ) -> list[RunSpec]:
        """Not-yet-dispatched nodes whose deps are all resolved.

        ``_deps_satisfied`` may add to ``skipped`` (the skip cascade). Order follows
        plan/declaration order (deterministic). When ``defer_bind`` (a boundary hook is
        wired), ``bind_after_deps`` nodes are excluded — they are never dispatched
        unbound and resolve only via the bind boundary (:meth:`_bind_pending`); with no
        hook the marker is inert and such a node dispatches like any other.
        """
        ready: list[RunSpec] = []
        for node in plan.nodes:
            if node.run_id in dispatched or node.run_id in skipped:
                continue
            if defer_bind and node.bind_after_deps:
                continue
            if self._deps_satisfied(plan, node, completed, skipped):
                ready.append(node)
        return ready

    def _bind_pending(
        self,
        plan: RunPlan,
        completed: Mapping[str, RunState],
        skipped: set[str],
        dispatched: set[str],
    ) -> list[RunSpec]:
        """Late-bound (``bind_after_deps``) nodes whose deps are all resolved but which
        are not yet finalised — the host must bind / yield / abort before they run.

        Mirrors :meth:`_select_ready`'s gate for the un-dispatchable late-bound nodes it
        deliberately excludes, and shares :meth:`_deps_satisfied` (so the skip cascade
        still reaches a late-bound node whose upstream skip-failed). Empty for any plan
        with no ``bind_after_deps`` node, so the bind boundary stays inert there.
        """
        ready: list[RunSpec] = []
        for node in plan.nodes:
            if not node.bind_after_deps:
                continue
            if node.run_id in dispatched or node.run_id in skipped:
                continue
            if self._deps_satisfied(plan, node, completed, skipped):
                ready.append(node)
        return ready

    def _scope_pending(
        self,
        plan: RunPlan,
        completed: Mapping[str, RunState],
    ) -> list[RunSpec]:
        """COMPLETED nodes carrying an unconsumed reactive-boundary escalation — a 职责/范围
        deviation (``escalate kind=scope``) OR a 依赖缺口·卡在缺输入 (``escalate kind=dep``,
        §2.4) — the SCOPE boundary's triggers (自底向上反应臂). Both ride the SAME boundary:
        the CEO/lead re-steers (scope) or replan(add)s a producer (dep) for the un-run tail.
        A consumed signal (already surfaced at a prior boundary) is skipped, so each yields the
        host exactly once. Empty for any plan whose completed nodes raised no scope/dep
        escalation, so the boundary stays inert there.
        """
        ready: list[RunSpec] = []
        for node in plan.nodes:
            state = completed.get(node.run_id)
            if state is None or state.phase is not RunPhase.COMPLETED:
                continue
            if any(
                e.get("kind") in ("scope", "dep") and not e.get("consumed")
                for e in state.escalations
            ):
                ready.append(node)
        return ready

    @staticmethod
    def _failure_cascades(dep: RunSpec | None, dep_state: RunState | None) -> bool:
        """Whether a FAILED dep with ``on_failure`` in ``{skip, retry}`` blocks a
        *strict* (``require_upstream``) dependent.

        ``degrade`` does not. ``CANCELLED`` is handled via :meth:`_cancel_cascades`.
        """
        if dep is None or dep_state is None:
            return False
        if dep_state.phase is not RunPhase.FAILED:
            return False
        return dep.policy.on_failure in ("skip", "retry")

    @staticmethod
    def _cancel_cascades(spec: RunSpec, dep_state: RunState | None) -> bool:
        """Whether a CANCELLED dep blocks a *strict* dependent.

        Lenient fan-in (default) ignores cancel here — :meth:`_deps_satisfied`
        only requires ≥1 COMPLETED upstream. ``force_continue`` always wins.
        """
        if dep_state is None or dep_state.phase is not RunPhase.CANCELLED:
            return False
        if bool(getattr(spec, "force_continue", False)):
            return False
        return bool(getattr(spec, "require_upstream", False))

    @staticmethod
    def _upstream_success_count(
        spec: RunSpec,
        completed: Mapping[str, RunState],
    ) -> int:
        return sum(
            1
            for dep_id in spec.depends_on
            if (st := completed.get(dep_id)) is not None and st.phase is RunPhase.COMPLETED
        )

    @staticmethod
    def _is_hard_absence(
        dep: RunSpec | None,
        dep_state: RunState | None,
        *,
        in_skipped: bool,
    ) -> bool:
        """True when a resolved dep counts as a hard absence for lenient fan-in.

        ``FAILED`` + ``degrade`` is soft (old best-effort path): dependent may
        still run with zero COMPLETED upstreams. Cancel / skip / retry-fail /
        cascade-skipped are hard.
        """
        if in_skipped:
            return True
        if dep_state is None:
            return True
        if dep_state.phase is RunPhase.COMPLETED:
            return False
        if dep_state.phase is RunPhase.CANCELLED:
            return True
        if dep_state.phase is RunPhase.FAILED:
            return not (dep is not None and dep.policy.on_failure == "degrade")
        if dep_state.phase is RunPhase.SKIPPED:
            return True
        return True

    @staticmethod
    def _deps_satisfied(
        plan: RunPlan,
        spec: RunSpec,
        completed: Mapping[str, RunState],
        skipped: set[str],
    ) -> bool:
        """Whether ``spec`` may run: every dep resolved (completed/failed/skipped)
        and the node itself not (transitively) skipped.

        Fan-in rules (取消≠失败; 汇聚默认宽松):
        - Default (``require_upstream=False``): ≥1 upstream COMPLETED → run.
          Zero successes → skip unless ``force_continue`` or only soft
          (``degrade``) absences remain.
        - Strict (``require_upstream=True``): any FAILED dep with
          ``on_failure`` in ``{skip, retry}``, any CANCELLED dep (unless
          ``force_continue``), or any still-skipped dep → cascade-skip.
        """
        for dep_id in spec.depends_on:
            if dep_id not in completed and dep_id not in skipped:
                return False

        if bool(getattr(spec, "require_upstream", False)):
            for dep_id in spec.depends_on:
                if dep_id in skipped:
                    skipped.add(spec.run_id)
                    return False
                dep = plan.by_id(dep_id)
                dep_state = completed.get(dep_id)
                if dep_state is not None and dep_state.phase is RunPhase.CANCELLED:
                    if WaveScheduler._cancel_cascades(spec, dep_state):
                        skipped.add(spec.run_id)
                        return False
                    continue
                if WaveScheduler._failure_cascades(dep, dep_state):
                    skipped.add(spec.run_id)
                    return False
            return spec.run_id not in skipped

        # Lenient: ≥1 successful delivery; else force_continue or only soft absences.
        if not spec.depends_on:
            return spec.run_id not in skipped
        if WaveScheduler._upstream_success_count(spec, completed) >= 1:
            return spec.run_id not in skipped
        if bool(getattr(spec, "force_continue", False)):
            return spec.run_id not in skipped
        has_hard = any(
            WaveScheduler._is_hard_absence(
                plan.by_id(dep_id),
                completed.get(dep_id),
                in_skipped=dep_id in skipped,
            )
            for dep_id in spec.depends_on
        )
        if has_hard:
            skipped.add(spec.run_id)
            return False
        return spec.run_id not in skipped

    def _propagate_skip(
        self,
        plan: RunPlan,
        failed_id: str,
        skipped: set[str],
        dispatched: set[str],
    ) -> None:
        """Cascade-skip *strict* (``require_upstream``) dependents of ``failed_id``.

        Lenient dependents are left for :meth:`_deps_satisfied` so a summarizer
        with other successful upstreams still runs.
        """
        for spec in plan.nodes:
            if (
                failed_id in spec.depends_on
                and spec.run_id not in skipped
                and spec.run_id not in dispatched
                and bool(getattr(spec, "require_upstream", False))
            ):
                skipped.add(spec.run_id)
                self._propagate_skip(plan, spec.run_id, skipped, dispatched)

    def _propagate_cancel_skip(
        self,
        plan: RunPlan,
        cancelled_id: str,
        skipped: set[str],
        dispatched: set[str],
    ) -> None:
        """Cascade-skip *strict* dependents of a CANCELLED node.

        Lenient fan-in waits for remaining upstreams; only ``require_upstream``
        (and not ``force_continue``) keeps the old cancel-cascade-skip.
        """
        for spec in plan.nodes:
            if (
                cancelled_id in spec.depends_on
                and spec.run_id not in skipped
                and spec.run_id not in dispatched
                and bool(getattr(spec, "require_upstream", False))
                and not bool(getattr(spec, "force_continue", False))
            ):
                skipped.add(spec.run_id)
                logger.info(
                    "wave.cancel_cascade_skip",
                    cancelled=cancelled_id,
                    skipped_run=spec.run_id,
                )
                self._propagate_cancel_skip(plan, spec.run_id, skipped, dispatched)

    def _revive_cascade_skips(
        self,
        plan: RunPlan,
        completed: Mapping[str, RunState],
        skipped: set[str],
        dispatched: set[str],
    ) -> None:
        """Un-skip nodes whose cascade reason no longer holds after edge rewrites.

        When CEO merge / replan adds a node with ``replaces_run_id``, dependents'
        ``depends_on`` point at the replacement; they must leave ``skipped`` so the
        ready-scan can wait on the new dep (instead of staying permanently skipped).
        """
        changed = True
        while changed:
            changed = False
            for rid in list(skipped):
                if rid in completed:
                    continue
                node = plan.by_id(rid)
                if node is None:
                    continue
                # Bind no-progress force-skip leaves ``bind_after_deps`` set — not a
                # cascade-from-failure; do not revive (would re-fire the bind boundary).
                if node.bind_after_deps:
                    continue
                if self._still_cascade_blocked(plan, node, completed, skipped):
                    continue
                skipped.discard(rid)
                dispatched.discard(rid)
                changed = True

    @staticmethod
    def _still_cascade_blocked(
        plan: RunPlan,
        node: RunSpec,
        completed: Mapping[str, RunState],
        skipped: set[str],
    ) -> bool:
        """True when ``node`` must stay skipped under current fan-in rules."""
        if bool(getattr(node, "require_upstream", False)):
            for dep_id in node.depends_on:
                if dep_id in skipped:
                    return True
                dep_state = completed.get(dep_id)
                if dep_state is not None and dep_state.phase is RunPhase.CANCELLED:
                    if WaveScheduler._cancel_cascades(node, dep_state):
                        return True
                    continue
                if WaveScheduler._failure_cascades(plan.by_id(dep_id), dep_state):
                    return True
            return False
        # Lenient: blocked while zero successes, not force_continue, and at least
        # one hard absence — and every dep is already resolved (otherwise wait).
        if bool(getattr(node, "force_continue", False)):
            return False
        for dep_id in node.depends_on:
            if dep_id not in completed and dep_id not in skipped:
                return False  # still waiting — revive so ready-scan can wait
        if WaveScheduler._upstream_success_count(node, completed) >= 1:
            return False
        return any(
            WaveScheduler._is_hard_absence(
                plan.by_id(dep_id),
                completed.get(dep_id),
                in_skipped=dep_id in skipped,
            )
            for dep_id in node.depends_on
        )
