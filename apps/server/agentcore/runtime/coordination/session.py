"""Coordination session: event queue, budget, timeouts, and durable snapshot.

Root-CEO only (Phase 2+). Lead nesting stays on the blocking path.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# Cap for coordinating-budget *telemetry counters* (progress + decision pools).
# Pools are observational only (批次 4)：计数与日志保留，不闸唤醒 / 不假限流。
# Necessary vs routine classification still drives *merge* batching (accumulate), not a hard stop.
DEFAULT_COORDINATION_BUDGET = 8
MAX_COORDINATION_BUDGET = 16
# 决策池保底切分口径（遥测分账用）：即便总额很小，也给必要决策类至少这么多记账槽。
_MIN_DECISION_BUDGET = 3

# Interjection stash keys safe to persist in the coordination journal snapshot.
# ``llm_credentials`` must never enter durable state (re-resolved on resume).
_INTERJECTION_SNAPSHOT_KEYS = frozenset(
    {
        "content",
        "user_id",
        "conversation_id",
        "attachments",
        "requires_tools",
        "x_client_platform",
        "llm_supports_tools",
    }
)


def coordination_budget_for_batch(node_count: int) -> int:
    """Scale telemetry budget with batch size: ``max(8, nodes+4)``, capped at 16."""
    return min(MAX_COORDINATION_BUDGET, max(DEFAULT_COORDINATION_BUDGET, node_count + 4))


def split_coordination_budget(total: int) -> tuple[int, int]:
    """Split a total coordination budget into ``(progress, decision)`` telemetry pools.

    决策池取 ``max(_MIN_DECISION_BUDGET, total // 3)``（不超过总额），其余归进度池；两池之和
    恒等于 ``total``。仅作唤醒分类计数 / 日志口径，不闸 CEO 唤醒。
    """
    total = max(0, int(total))
    decision = min(total, max(_MIN_DECISION_BUDGET, total // 3))
    progress = total - decision
    return progress, decision


# 编译期常量（前缀缓存 / 默认值友好）：默认与上限总额各自切分出的两池额度。
DEFAULT_PROGRESS_BUDGET, DEFAULT_DECISION_BUDGET = split_coordination_budget(
    DEFAULT_COORDINATION_BUDGET
)
MAX_PROGRESS_BUDGET, MAX_DECISION_BUDGET = split_coordination_budget(MAX_COORDINATION_BUDGET)


def _budget_pools_from_dict(data: dict[str, Any]) -> tuple[int, int]:
    """Read the two-pool budget from a snapshot dict, tolerating legacy snapshots.

    新快照只带 ``progress_budget_remaining`` + ``decision_budget_remaining``（Wave3a 起
    不再双写合计）；旧快照只有单一 ``budget_remaining`` → 用
    :func:`split_coordination_budget` 切分，让旧的持久化快照也能干净恢复。
    """
    if "progress_budget_remaining" in data or "decision_budget_remaining" in data:
        progress = int(data.get("progress_budget_remaining", DEFAULT_PROGRESS_BUDGET))
        decision = int(data.get("decision_budget_remaining", DEFAULT_DECISION_BUDGET))
        return max(0, progress), max(0, decision)
    legacy = int(data.get("budget_remaining", DEFAULT_COORDINATION_BUDGET))
    return split_coordination_budget(legacy)


# Fallback per-worker wall-clock before a timeout *notification* (CEO decides; no auto-cancel).
# Prefer ``RunPolicy.timeout_s`` from worker_budget backstop (or CEO-explicit ``timeout_ms``).
DEFAULT_WORKER_TIMEOUT_S = 1200.0
# Fraction of threshold at which the worker gets a wind-down warn (handoff-in-1-round)
# before the CEO-facing TIMEOUT notification. Overridden by engine settings at arm time.
DEFAULT_TIMEOUT_WARN_RATIO = 0.75

# Registry keyed by root-turn ``execution_id`` (captain + all workers share one id).
# Module-level dict — not a ContextVar holding the session — because ``execute_tools``
# runs each tool under ``asyncio.gather``, which copies the context: a session set
# inside ``delegate`` would be invisible to the parent CEO ``react_loop``. The dict
# is a shared object visible across gather; the key isolates concurrent turns.
# ``current_execution_id`` is set at turn entry (before gather) so the captain wait
# path can resolve without threading execution_id through the whole loop.
_sessions: dict[str, CoordinationSession] = {}
# Reverse index: conversation_id → execution_id for mid-flight message routing
# (POST …/messages while a coordination turn is live).
_by_conversation: dict[str, str] = {}
current_execution_id: ContextVar[str | None] = ContextVar("current_execution_id", default=None)


class CoordinationEventKind(StrEnum):
    WORKER_COMPLETED = "worker_completed"
    NOTE_POSTED = "note_posted"
    ESCALATION = "escalation"
    TIMEOUT = "timeout"
    ALL_COMPLETED = "all_completed"
    BOUNDARY_YIELD = "boundary_yield"
    # Mid-flight user message injected into the live coordination window (CEO routes).
    USER_INTERJECTION = "user_interjection"
    # Background drive cancelled (process kill / soft-stop). Wake host without
    # implying every worker finished — distinct from ALL_COMPLETED.
    DRIVE_CANCELLED = "drive_cancelled"


@dataclass(frozen=True, slots=True)
class CoordinationEvent:
    kind: CoordinationEventKind
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CancelResolution:
    """Outcome of resolving a CEO-supplied ``cancel_worker`` arg to a full run_id.

    The CEO only ever sees role / short names in coordination events, but the
    scheduler cancels by exact engine-minted run_id — so a short name must be
    resolved back against the in-flight worker registry first.

    - ``run_id`` — the resolved full run_id, or ``None`` when unresolved.
    - ``reason`` — how it resolved (``exact`` / ``suffix`` / ``role``) or why it
      failed (``ambiguous`` / ``not_found``).
    - ``candidates`` — colliding full run_ids when ``ambiguous`` (empty otherwise).
    """

    run_id: str | None
    reason: str
    candidates: tuple[str, ...] = ()


@dataclass
class CoordinationSnapshot:
    """Durable slice restored on ask_user resume / process restart."""

    execution_id: str
    draft: str = ""
    conversation_id: str = ""
    completed_run_ids: list[str] = field(default_factory=list)
    # 两池遥测计数（进度池 + 决策池）。旧快照只有单一 ``budget_remaining`` → from_dict 兼容切分。
    progress_budget_remaining: int = DEFAULT_PROGRESS_BUDGET
    decision_budget_remaining: int = DEFAULT_DECISION_BUDGET
    total_workers: int = 0
    active: bool = True
    cancel_run_ids: list[str] = field(default_factory=list)
    pending_events: list[dict[str, Any]] = field(default_factory=list)
    # D1: blocking escalate awaiting CEO — survives ask_user soft-stop so resume can
    # resolve_escalation (or re-armed workers pick up a stashed answer).
    pending_arbitrations: list[dict[str, Any]] = field(default_factory=list)
    resolved_arbitrations: list[dict[str, Any]] = field(default_factory=list)
    # 批次 4 快照扩容：活计划 / 插话队列（无凭据）/ 注入与收口标记。
    live_plan: dict[str, Any] | None = None
    pending_interjections: list[dict[str, Any]] = field(default_factory=list)
    all_completed_injected: bool = False
    harvest_scheduled: bool = False
    terminal_posted: bool = False
    settled_via: str | None = None
    turn_attached: bool = True
    user_stopped: bool = False
    saw_first_completion: bool = False
    # C3: ownership ledger snapshot (v2 nested ``{owners, written}`` or legacy flat).
    file_ownership: dict[str, Any] = field(default_factory=dict)

    @property
    def budget_remaining(self) -> int:
        """两池合计（向后兼容读法；分池语义见 progress_/decision_budget_remaining）。"""
        return self.progress_budget_remaining + self.decision_budget_remaining

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "draft": self.draft,
            "conversation_id": self.conversation_id,
            "completed_run_ids": list(self.completed_run_ids),
            "progress_budget_remaining": self.progress_budget_remaining,
            "decision_budget_remaining": self.decision_budget_remaining,
            # Wave3a：停写合计字段 ``budget_remaining``（开发期减噪）。旧读者仍靠
            # ``from_dict`` / ``split_coordination_budget`` 读兼容——勿删读路径。
            "total_workers": self.total_workers,
            "active": self.active,
            "cancel_run_ids": list(self.cancel_run_ids),
            "pending_events": list(self.pending_events),
            "pending_arbitrations": list(self.pending_arbitrations),
            "resolved_arbitrations": list(self.resolved_arbitrations),
            "live_plan": self.live_plan,
            "pending_interjections": list(self.pending_interjections),
            "all_completed_injected": self.all_completed_injected,
            "harvest_scheduled": self.harvest_scheduled,
            "terminal_posted": self.terminal_posted,
            "settled_via": self.settled_via,
            "turn_attached": self.turn_attached,
            "user_stopped": self.user_stopped,
            "saw_first_completion": self.saw_first_completion,
            "file_ownership": dict(self.file_ownership),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CoordinationSnapshot | None:
        if not data or not isinstance(data, dict):
            return None
        execution_id = str(data.get("execution_id") or "").strip()
        if not execution_id:
            return None
        progress, decision = _budget_pools_from_dict(data)
        live_plan = data.get("live_plan")
        if live_plan is not None and not isinstance(live_plan, dict):
            live_plan = None
        settled_via = data.get("settled_via")
        if settled_via is not None:
            settled_via = str(settled_via).strip() or None
        raw_own = data.get("file_ownership")
        file_ownership: dict[str, Any] = {}
        if isinstance(raw_own, dict):
            # Pass through v2 nested snapshots; coerce legacy flat path→owner.
            if raw_own.get("_v") == 2 or isinstance(raw_own.get("owners"), dict):
                file_ownership = dict(raw_own)
            else:
                file_ownership = {
                    str(k): str(v)
                    for k, v in raw_own.items()
                    if isinstance(k, str) and v is not None and str(v).strip()
                }
        return cls(
            execution_id=execution_id,
            draft=str(data.get("draft") or ""),
            conversation_id=str(data.get("conversation_id") or ""),
            completed_run_ids=[str(x) for x in (data.get("completed_run_ids") or [])],
            progress_budget_remaining=progress,
            decision_budget_remaining=decision,
            total_workers=int(data.get("total_workers") or 0),
            active=bool(data.get("active", True)),
            cancel_run_ids=[str(x) for x in (data.get("cancel_run_ids") or [])],
            pending_events=list(data.get("pending_events") or []),
            pending_arbitrations=list(data.get("pending_arbitrations") or []),
            resolved_arbitrations=list(data.get("resolved_arbitrations") or []),
            live_plan=live_plan,
            pending_interjections=[
                dict(x) for x in (data.get("pending_interjections") or []) if isinstance(x, dict)
            ],
            all_completed_injected=bool(data.get("all_completed_injected", False)),
            harvest_scheduled=bool(data.get("harvest_scheduled", False)),
            terminal_posted=bool(data.get("terminal_posted", False)),
            settled_via=settled_via,
            turn_attached=bool(data.get("turn_attached", True)),
            user_stopped=bool(data.get("user_stopped", False)),
            saw_first_completion=bool(data.get("saw_first_completion", False)),
            file_ownership=file_ownership,
        )


def should_enter_coordination(
    *,
    coordinate: bool,
    worker_count: int,
    finalize: bool,
    depth: int,
    has_checkpoint: bool = False,
    checkpoint_enabled: bool = False,
) -> bool:
    """Gate: ≥2 workers + root CEO + not finalize; opt out with ``coordinate=False``.

    Callers default ``coordinate`` to True when the LLM omits the arg; only an
    explicit false falls back to classic blocking. Solo / nested lead / finalize
    still never enter.

    When the batch contains ``checkpoint_after`` nodes **and** the turn's checkpoint
    gate is open, stay on classic blocking drive so durable plan_review cards fire.
    Gate-off (evals / ``approvals_enabled=False``) leaves coordination unchanged.

    **Invariant B**: CEO arbitration (``resolve_escalation`` / ``awaiting=ceo``)
    is available iff a coordination session is active. Solo blocking escalate
    therefore hangs on the **user**, never the CEO — otherwise worker↔CEO deadlock
    (CEO blocked inside ``delegate``, worker waiting for ``resolve_escalation``).
    """
    if coordinate is False:
        return False
    if depth != 0:
        return False
    if finalize:
        return False
    if has_checkpoint and checkpoint_enabled:
        return False
    return worker_count >= 2


@dataclass
class CoordinationSession:
    """In-process coordination state for one non-blocking delegate batch."""

    execution_id: str
    total_workers: int
    # 两池遥测计数（同一总额切成两本账，不扩容、不闸唤醒）：
    # - 进度池：例行进展（worker 完成 / note）唤醒计数。
    # - 决策池：必要决策（终局 / 升级 / 冲突 / 插话 / 单员超时 / 边界 / 派批）唤醒计数。
    progress_budget_remaining: int = DEFAULT_PROGRESS_BUDGET
    decision_budget_remaining: int = DEFAULT_DECISION_BUDGET
    draft: str = ""
    conversation_id: str = ""
    completed_run_ids: set[str] = field(default_factory=set)
    # Terminal FAILED run_ids (subset of completed) — pipeline health / idle brief.
    failed_run_ids: set[str] = field(default_factory=set)
    # FAILED / CANCELLED / SKIPPED — seats vacated for auto replaces_run_id fill.
    # Process-local (like failed_run_ids); seed path rehydrates from RunPhase.
    vacated_run_ids: set[str] = field(default_factory=set)
    # CEO progress-inject cursor: completed ids already named in a prior progress
    # block. Not snapshotted — restore seeds it to current completed (no re-dump).
    progress_reported_completed: set[str] = field(default_factory=set)
    cancel_ids: set[str] = field(default_factory=set)
    active: bool = True
    # True after all_completed has been injected into the CEO window.
    all_completed_injected: bool = False
    # Background WaveScheduler task (owned by drive); None until started.
    drive_task: asyncio.Task[Any] | None = None
    # ask_user soft-stop sets this before cancelling drive_task so the cancel
    # handler skips wake events (no ALL_COMPLETED / DRIVE_CANCELLED in the
    # hang-frame snapshot — resume re-drives unfinished workers from journal).
    soft_stop: bool = False
    # Turn ownership: True while the arming chat turn is still open. Teardown sets
    # False when preserving a live background drive so the drive's finally can
    # close+unregister after workers finish (lifecycle ≠ chat turn).
    turn_attached: bool = True
    # Host turn journal writer bound at arm time — DURABLE display facts keep
    # appending here after the arming turn's ContextVar is reset (pillar A).
    host_journal_writer: Any | None = field(default=None, repr=False)
    host_turn_id: str = ""
    # Set when a harvest closing turn has been scheduled (idempotent).
    harvest_scheduled: bool = False
    # Drive posted ALL_COMPLETED / DRIVE_CANCELLED (终态对账前置条件).
    terminal_posted: bool = False
    # 终态收敛路径：attached_inject | harvest | user_stop；清空前未收敛 → error 告警.
    settled_via: str | None = None
    # Live RunPlan owned by the active drive — mid-coordination secondary
    # ``delegate`` appends workers here (same graph / same session).
    live_plan: Any | None = field(default=None, repr=False)
    _queue: asyncio.Queue[CoordinationEvent] = field(default_factory=asyncio.Queue, repr=False)
    # Events already drained but not yet consumed by an LLM round (merge buffer).
    _pending: list[CoordinationEvent] = field(default_factory=list, repr=False)
    # Wakes ``wait_events`` when snapshot/drain moves queue items into ``_pending``
    # (otherwise a blocked ``queue.get`` would miss them until timeout).
    _wake: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    # First worker completion always forces a decision point.
    _saw_first_completion: bool = False
    # Per-worker wall-clock timers (notify-only; never auto-cancel).
    _worker_started_at: dict[str, float] = field(default_factory=dict, repr=False)
    _timeout_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict, repr=False)
    # In-flight worker registry (full run_id → role) for cancel_worker short→full
    # resolution. Populated on ``arm_worker_timeout`` (every dispatch), cleared on
    # disarm / completion. NOT snapshotted: resume re-dispatches unfinished workers,
    # which re-arm and re-register — so a completed worker is never resolvable.
    _running_workers: dict[str, str] = field(default_factory=dict, repr=False)
    # Worker busy stamps (run_id → "llm" | "tool" | "verify"):
    # - llm/tool: short in-flight work; idle-patrol defers (勿误唤醒).
    # - verify: minute-level bounded verify (test_run); still shown in progress
    #   summary, but does NOT count as has_inflight_work — CEO may patrol /
    #   cancel_worker instead of parking behind wall+0. 不快照。
    _busy_workers: dict[str, str] = field(default_factory=dict, repr=False)
    # Sibling verify coalesce (same execution): fingerprint → inflight Future /
    # completed ToolResult snapshot. Process-local; not snapshotted (resume
    # re-runs unfinished workers). Generation bumps on successful land so a
    # still-running verify cannot re-poison the cache after disk changed. 不快照。
    _verify_inflight: dict[str, asyncio.Future[Any]] = field(
        default_factory=dict, repr=False
    )
    _verify_cache: dict[str, Any] = field(default_factory=dict, repr=False)
    _verify_generation: int = field(default=0, repr=False)
    # Explicit user /stop cascaded cancel — release_turn_coordination must clear
    # (not detach) so the background drive does not outlive the stopped turn.
    user_stopped: bool = False
    # Note-wall coordination mode for this batch (``wall`` | ``none``). Used by idle
    # wait to keep the main turn open when wall + 0 completions (要等齐).
    coordination: str = "none"
    _timeout_notified: set[str] = field(default_factory=set, repr=False)
    # B·超时预警：先于 CEO TIMEOUT 通知，供 worker react_loop 消费进入收尾窗口。
    _timeout_warned: set[str] = field(default_factory=set, repr=False)
    _timeout_wind_down_pending: set[str] = field(default_factory=set, repr=False)
    # 「真正进入过 timeout wind-down」的痕迹：仅在 consume_timeout_wind_down 被引擎消费
    # （工具面实际被收窄）时记入，pending 未消费不算。与 _timeout_notified 同生命周期
    # （arm 重置、disarm 不清），供 coordinated_executor 判超时是否真造成交付缩水。不快照。
    _timeout_wind_down_entered: set[str] = field(default_factory=set, repr=False)
    # Hard-timeout force-cancel via cancel_ids (宽限耗尽 / 宽限墙钟)。不快照。
    _timeout_force_cancelled: set[str] = field(default_factory=set, repr=False)
    # Dedupe escalation injections (live escalate + completion harvest + SCOPE boundary).
    _escalation_keys: set[str] = field(default_factory=set, repr=False)
    # D1: blocking escalate → CEO arbitration. run_id → live bridge metadata.
    pending_arbitrations: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Answers stashed when the live Future is gone (ask_user soft-stop cancelled the worker);
    # re-armed workers pick these up on the next escalate(blocking=true).
    resolved_arbitrations: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Mid-flight user interjections awaiting CEO disposition. Credentials are
    # process-local only — journal snapshots strip ``llm_credentials``.
    pending_interjections: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    # Ids injected into a CEO wake and not yet addressed/queued/failed (process-local).
    awaiting_disposition: set[str] = field(default_factory=set, repr=False)
    # Terminal disposition already emitted (idempotent queue_user_message after close).
    dispositioned_interjections: set[str] = field(default_factory=set, repr=False)
    # Live SSE sink for coordination UX (``coordination_wait``). Set by host when
    # arming; not snapshotted — resume re-attaches from the live tool sink.
    event_sink: Any | None = field(default=None, repr=False)
    # 唤醒节流基线（monotonic 秒）：每次真正唤醒 CEO 出手后 stamp。进展事件攒批以此为
    # 参照——「距上次唤醒 <合并窗口 且 未攒够阈值」时 hold 合并，避免每个 worker 完成都醒。
    # None = 尚未唤醒过（首个完成事件本就是必要决策点，立即唤醒、不攒批）。不快照。
    last_wake_monotonic: float | None = field(default=None, repr=False)
    # 空转巡查连续超时次数：每次「无任何新事件」的 idle 超时 +1，有真实事件即清零。
    # idle 等待超时按 2**streak 退避降频，避免无事件时反复烧全量 LLM 轮。不快照。
    idle_streak: int = 0
    # 疑似缺依赖提示（builder.suspect_missing_dep 搭车）：建图时收集，首次注入随团队
    # 事件简报一并呈现给 CEO 后清空——搭车既有注入通道，不新增独立唤醒。不快照。
    dep_advisories: list[str] = field(default_factory=list, repr=False)
    # C3 文件归属账本（execution 生命周期；与批次 WriteCoordinator 统一为一本账）。
    # 进快照可恢复；嵌套子队经 resolve_write_coordinator 共享本表。
    file_ownership: Any | None = field(default=None, repr=False)

    def ensure_file_ownership(self) -> Any:
        """Lazy-init the session ownership ledger (one book for dispatch + write)."""
        if self.file_ownership is None:
            from agentcore.workspace.write_claims import WriteCoordinator

            self.file_ownership = WriteCoordinator()
        return self.file_ownership

    def register_arbitration(
        self,
        run_id: str,
        *,
        escalation_id: str,
        conversation_id: str,
        question: str = "",
        assumption: str = "",
        kind: str = "normal",
        ownership_paths: list[str] | None = None,
        lock_owner_run_id: str = "",
        escalator_is_lock_owner_nested_child: bool | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "run_id": run_id,
            "escalation_id": escalation_id,
            "conversation_id": conversation_id,
            "question": question,
            "assumption": assumption,
            "kind": kind,
        }
        if ownership_paths:
            payload["ownership_paths"] = list(ownership_paths)
        if lock_owner_run_id:
            payload["lock_owner_run_id"] = lock_owner_run_id
        if escalator_is_lock_owner_nested_child is not None:
            payload["escalator_is_lock_owner_nested_child"] = bool(
                escalator_is_lock_owner_nested_child
            )
        self.pending_arbitrations[run_id] = payload

    def get_arbitration(self, run_id: str) -> dict[str, Any] | None:
        return self.pending_arbitrations.get(run_id)

    def clear_arbitration(self, run_id: str) -> None:
        self.pending_arbitrations.pop(run_id, None)

    def stash_resolution(
        self,
        run_id: str,
        *,
        answer: str,
        via_user: bool = False,
        escalation_id: str = "",
    ) -> None:
        payload: dict[str, Any] = {
            "run_id": run_id,
            "answer": answer,
            "via_user": via_user,
        }
        if escalation_id:
            payload["escalation_id"] = escalation_id
        elif run_id in self.pending_arbitrations:
            eid = self.pending_arbitrations[run_id].get("escalation_id")
            if eid:
                payload["escalation_id"] = eid
        self.resolved_arbitrations[run_id] = payload
        self.pending_arbitrations.pop(run_id, None)

    def take_stashed_resolution(self, run_id: str) -> dict[str, Any] | None:
        return self.resolved_arbitrations.pop(run_id, None)

    def post(self, event: CoordinationEvent) -> bool:
        """Enqueue ``event``. Returns False when dropped (inactive / escalation dedupe)."""
        if not self.active and event.kind not in (
            CoordinationEventKind.ALL_COMPLETED,
            CoordinationEventKind.DRIVE_CANCELLED,
        ):
            return False
        if event.kind is CoordinationEventKind.ESCALATION:
            key = (
                f"{event.payload.get('run_id') or ''}|"
                f"{event.payload.get('kind') or ''}|"
                f"{(event.payload.get('question') or event.payload.get('summary') or '')[:120]}"
            )
            if key in self._escalation_keys:
                return False
            self._escalation_keys.add(key)
        if event.kind in (
            CoordinationEventKind.ALL_COMPLETED,
            CoordinationEventKind.DRIVE_CANCELLED,
        ):
            self.terminal_posted = True
        self._queue.put_nowait(event)
        logger.debug(
            "coordination.event_posted",
            kind=event.kind.value,
            execution_id=self.execution_id,
        )
        return True

    def mark_settled(self, via: str) -> None:
        """Record which path consumed the terminal (attached inject / harvest / stop)."""
        label = (via or "").strip()
        if not label:
            return
        if self.settled_via and self.settled_via != label:
            logger.info(
                "coordination.settled_via_replaced",
                execution_id=self.execution_id,
                prior=self.settled_via,
                via=label,
            )
        self.settled_via = label

    def check_terminal_settlement(self) -> None:
        """终态对账：terminal 必须收敛到附着注入或收口 harvest（user_stop 豁免）。"""
        if self.settled_via:
            return
        if self.user_stopped:
            self.settled_via = "user_stop"
            return
        if self.all_completed_injected:
            self.settled_via = "attached_inject"
            return
        if self.harvest_scheduled:
            self.settled_via = "harvest"
            return
        if not self.terminal_posted:
            return
        logger.error(
            "coordination.terminal_unsettled",
            execution_id=self.execution_id,
            conversation_id=self.conversation_id or "",
            completed=len(self.completed_run_ids),
            total=self.total_workers,
            turn_attached=self.turn_attached,
            harvest_scheduled=self.harvest_scheduled,
            all_completed_injected=self.all_completed_injected,
            detail=("终态对账失败：execution 已投递终态，但未收敛到附着回合注入或收口 harvest。"),
        )

    def mark_worker_completed(self, run_id: str) -> None:
        self.completed_run_ids.add(run_id)
        self.disarm_worker_timeout(run_id)
        self._handoff_ownership_on_complete(run_id)

    def _handoff_ownership_on_complete(self, run_id: str) -> None:
        """交接式写权：完成后把独占下游 artifact 路径交给唯一依赖方。"""
        rid = (run_id or "").strip()
        if not rid or self.file_ownership is None or self.live_plan is None:
            return
        try:
            from agentcore.runtime.coordination.append_guard import (
                handoff_owned_paths_on_complete,
            )
            from agentcore.workspace.write_claims import file_ownership_v2_enabled

            if not file_ownership_v2_enabled():
                return
            moved = handoff_owned_paths_on_complete(
                self.live_plan,
                self.ensure_file_ownership(),
                rid,
                completed_run_ids=self.completed_run_ids,
            )
        except Exception:  # noqa: BLE001 — never break completion
            return
        if not moved:
            return
        try:
            from agentcore.core.logging import get_logger

            get_logger(__name__).info(
                "file_ownership.completion_handoff",
                run_id=rid,
                execution_id=self.execution_id,
                transfers=[{"path": path, "new_owner": new_owner} for path, new_owner in moved],
            )
        except Exception:  # noqa: BLE001
            pass

    def take_progress_delta(self) -> set[str]:
        """Completed run_ids not yet named in a CEO progress block; advances cursor."""
        delta = set(self.completed_run_ids) - self.progress_reported_completed
        self.progress_reported_completed |= delta
        return delta

    def request_cancel(self, run_id: str) -> None:
        self.cancel_ids.add(run_id)

    def running_workers(self) -> list[tuple[str, str]]:
        """(full run_id, role) for every in-flight worker, sorted by run_id.

        Backs ``cancel_worker`` error listings so the CEO sees exactly which
        workers it can still cancel (and their full run_ids to copy).
        """
        return sorted(self._running_workers.items())

    def mark_worker_busy(self, run_id: str, kind: str) -> None:
        """Stamp that ``run_id`` is inside an LLM stream, tool call, or verify."""
        rid = (run_id or "").strip()
        if not rid or rid not in self._running_workers:
            return
        label = kind if kind in ("llm", "tool", "verify") else "llm"
        self._busy_workers[rid] = label

    def clear_worker_busy(self, run_id: str) -> None:
        self._busy_workers.pop((run_id or "").strip(), None)

    def has_inflight_work(self) -> bool:
        """True when any worker holds a short LLM/tool call (not long verify)."""
        return any(kind in ("llm", "tool") for kind in self._busy_workers.values())

    def has_verify_busy(self) -> bool:
        """True when any registered worker is inside a bounded verify."""
        return any(kind == "verify" for kind in self._busy_workers.values())

    def worker_progress_summary(self) -> str:
        """Human lines for idle-patrol nudge: role / elapsed / busy-or-idle."""
        now = time.monotonic()
        lines: list[str] = []
        busy_label = {
            "llm": "LLM 调用中",
            "tool": "工具执行中",
            "verify": "有界验证中（可用 cancel_worker 打断）",
        }
        for run_id, role in self.running_workers():
            started = self._worker_started_at.get(run_id)
            elapsed = int(now - started) if started is not None else 0
            status = busy_label.get(self._busy_workers.get(run_id, ""), "轮间/无进行中调用")
            lines.append(f"  - 【{role}】run_id={run_id} 已运行 {elapsed}s · {status}")
        done = len(self.completed_run_ids)
        total = self.total_workers
        head = f"队员进展（已完成 {done}/{total}）："
        if not lines:
            return f"{head}无在跑队员。"
        return head + "\n" + "\n".join(lines)

    def invalidate_verify_cache(self, *, reason: str = "landed") -> int:
        """Drop cached verify results after the workspace changed.

        Clears ``_verify_cache`` and bumps ``_verify_generation`` so in-flight
        producers still finish for awaiters but do **not** re-enter the cache
        (avoids cancel storms while preventing stale greens).
        Returns how many cache entries were dropped.
        """
        dropped = len(self._verify_cache)
        self._verify_cache.clear()
        self._verify_generation += 1
        if dropped:
            with contextlib.suppress(Exception):
                logger.info(
                    "coordination.verify_cache_invalidated",
                    execution_id=self.execution_id,
                    reason=reason,
                    dropped=dropped,
                    generation=self._verify_generation,
                )
        return dropped

    async def coalesce_verify(
        self,
        fingerprint: str,
        runner: Any,
    ) -> tuple[Any, str]:
        """Run or join a sibling verify for ``fingerprint``.

        Returns ``(tool_result, source)`` where ``source`` is ``run`` | ``inflight``
        | ``cache``. Completed results (success or failure / budget) are cached for
        the rest of this execution so overlapping sibling ``test_run`` calls do not
        double-burn the minute-level budget. A land that bumps generation prevents
        a late producer from re-caching a pre-write result.
        """
        from dataclasses import replace

        key = (fingerprint or "").strip()
        if not key:
            result = await runner()
            return result, "run"

        cached = self._verify_cache.get(key)
        if cached is not None:
            return replace(cached), "cache"

        existing = self._verify_inflight.get(key)
        if existing is not None:
            shared = await existing
            return replace(shared), "inflight"

        generation = self._verify_generation
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._verify_inflight[key] = fut
        try:
            result = await runner()
            snap = replace(result)
            # Only cache when the workspace generation is unchanged since start.
            if self._verify_generation == generation:
                self._verify_cache[key] = snap
            if not fut.done():
                fut.set_result(snap)
            return result, "run"
        except BaseException as exc:
            if not fut.done():
                fut.set_exception(exc)
            raise
        finally:
            self._verify_inflight.pop(key, None)

    def resolve_cancel_target(self, raw: str) -> CancelResolution:
        """Resolve a CEO-supplied ``cancel_worker`` arg to a live worker's full run_id.

        The CEO only sees role / short names in coordination events, but the
        scheduler matches the engine-minted full run_id **exactly** — so a short
        name silently never cancels. Resolve tolerantly against in-flight workers:

        1. exact full run_id hit,
        2. else a unique ``_{raw}`` suffix match (short name = the run_id tail),
        3. else a unique role-name match.

        Multiple matches → ``ambiguous`` (candidates listed); none → ``not_found``.
        """
        target = (raw or "").strip()
        if not target:
            return CancelResolution(run_id=None, reason="not_found")
        if target in self._running_workers:
            return CancelResolution(run_id=target, reason="exact")
        suffix = f"_{target}"
        suffix_hits = sorted(rid for rid in self._running_workers if rid.endswith(suffix))
        if len(suffix_hits) == 1:
            return CancelResolution(run_id=suffix_hits[0], reason="suffix")
        role_hits = sorted(rid for rid, role in self._running_workers.items() if role == target)
        if len(role_hits) == 1:
            return CancelResolution(run_id=role_hits[0], reason="role")
        candidates = tuple(sorted(set(suffix_hits) | set(role_hits)))
        return CancelResolution(
            run_id=None,
            reason="ambiguous" if candidates else "not_found",
            candidates=candidates,
        )

    def _ended_run_ids(self) -> set[str]:
        """All session-terminal worker ids (any terminal phase counts as ended).

        ``completed_run_ids`` is the primary pool (host marks COMPLETED / FAILED /
        CANCELLED / SKIPPED here). ``vacated_run_ids`` / ``failed_run_ids`` are
        unioned defensively so vacated seats still resolve if a path only stamped
        those sets.
        """
        return set(self.completed_run_ids) | set(self.vacated_run_ids) | set(
            self.failed_run_ids
        )

    def resolve_ended_worker(self, raw: str) -> CancelResolution:
        """Resolve ``raw`` to a session worker that already finished.

        Used by ``cancel_worker`` for idempotent success when the target is no
        longer in ``_running_workers`` but is confirmed ended for this session.
        Terminal phases: COMPLETED / FAILED / SKIPPED / CANCELLED (and handoff
        ownership on complete). Matching mirrors :meth:`resolve_cancel_target`
        against :meth:`_ended_run_ids` (+ live_plan roles). Ambiguous / unknown →
        ``not_found`` / ``ambiguous``.
        """
        target = (raw or "").strip()
        if not target:
            return CancelResolution(run_id=None, reason="not_found")
        done = self._ended_run_ids()
        if target in done:
            return CancelResolution(run_id=target, reason="exact")
        suffix = f"_{target}"
        suffix_hits = sorted(rid for rid in done if rid.endswith(suffix))
        if len(suffix_hits) == 1:
            return CancelResolution(run_id=suffix_hits[0], reason="suffix")
        role_by_id: dict[str, str] = {}
        live = self.live_plan
        if live is not None:
            for node in getattr(live, "nodes", ()) or ():
                rid = getattr(node, "run_id", "") or ""
                if rid in done:
                    role_by_id[rid] = (getattr(node, "role", None) or rid).strip() or rid
        role_hits = sorted(rid for rid, role in role_by_id.items() if role == target)
        if len(role_hits) == 1:
            return CancelResolution(run_id=role_hits[0], reason="role")
        candidates = tuple(sorted(set(suffix_hits) | set(role_hits)))
        return CancelResolution(
            run_id=None,
            reason="ambiguous" if candidates else "not_found",
            candidates=candidates,
        )

    def resolve_pending_worker(self, raw: str) -> CancelResolution:
        """Resolve ``raw`` to a live_plan node that has not started and has not ended.

        Pending = on current ``live_plan``, not in ``_running_workers``, not in
        :meth:`_ended_run_ids`. Used by ``cancel_worker`` to withdraw a queued node
        (mark skipped / vacated) before Wave dispatches it. Matching mirrors
        :meth:`resolve_cancel_target` (exact / unique suffix / unique role).
        Ambiguous / unknown / no live_plan → ``not_found`` / ``ambiguous``.
        """
        target = (raw or "").strip()
        if not target:
            return CancelResolution(run_id=None, reason="not_found")
        live = self.live_plan
        if live is None:
            return CancelResolution(run_id=None, reason="not_found")
        nodes = list(getattr(live, "nodes", ()) or ())
        if not nodes:
            return CancelResolution(run_id=None, reason="not_found")
        ended = self._ended_run_ids()
        running = set(self._running_workers)
        pending: dict[str, str] = {}
        for node in nodes:
            rid = (getattr(node, "run_id", "") or "").strip()
            if not rid or rid in ended or rid in running:
                continue
            pending[rid] = (getattr(node, "role", None) or rid).strip() or rid
        if not pending:
            return CancelResolution(run_id=None, reason="not_found")
        if target in pending:
            return CancelResolution(run_id=target, reason="exact")
        suffix = f"_{target}"
        suffix_hits = sorted(rid for rid in pending if rid.endswith(suffix))
        if len(suffix_hits) == 1:
            return CancelResolution(run_id=suffix_hits[0], reason="suffix")
        role_hits = sorted(rid for rid, role in pending.items() if role == target)
        if len(role_hits) == 1:
            return CancelResolution(run_id=role_hits[0], reason="role")
        candidates = tuple(sorted(set(suffix_hits) | set(role_hits)))
        return CancelResolution(
            run_id=None,
            reason="ambiguous" if candidates else "not_found",
            candidates=candidates,
        )

    def vacate_pending_worker(self, run_id: str) -> None:
        """Formally withdraw a queued (not-yet-running) plan node.

        Stamps the seat as session-terminal SKIPPED (completed + vacated) and adds
        ``run_id`` to ``cancel_ids`` so Wave will not dispatch it (and will cancel
        if a race already launched). Does not touch other workers — never retargets.
        """
        rid = (run_id or "").strip()
        if not rid:
            return
        self.mark_worker_completed(rid)
        self.vacated_run_ids.add(rid)
        self.request_cancel(rid)

    def suggest_cancel_by_plan_role(self, raw: str) -> tuple[str, str] | None:
        """Hint-only: unique running worker sharing the live_plan role of ``raw``.

        Used when ``cancel_worker`` truly cannot resolve ``raw`` (not running, not
        ended). Looks up ``raw`` on ``live_plan`` (exact / unique suffix), then if
        that node's role has exactly one in-flight worker, returns
        ``(run_id, role)`` so the tool can name it — never auto-cancels.
        """
        target = (raw or "").strip()
        if not target:
            return None
        live = self.live_plan
        if live is None:
            return None
        nodes = list(getattr(live, "nodes", ()) or ())
        if not nodes:
            return None
        role: str | None = None
        exact = next(
            (
                n
                for n in nodes
                if (getattr(n, "run_id", "") or "").strip() == target
            ),
            None,
        )
        if exact is not None:
            role = (getattr(exact, "role", None) or "").strip() or None
        else:
            suffix = f"_{target}"
            suffix_nodes = [
                n
                for n in nodes
                if (getattr(n, "run_id", "") or "").endswith(suffix)
            ]
            if len(suffix_nodes) == 1:
                role = (getattr(suffix_nodes[0], "role", None) or "").strip() or None
        if not role:
            return None
        role_hits = sorted(
            rid for rid, r in self._running_workers.items() if r == role
        )
        if len(role_hits) != 1:
            return None
        return role_hits[0], role

    def arm_worker_timeout(
        self,
        run_id: str,
        *,
        role: str = "",
        timeout_s: float | int | None = None,
    ) -> None:
        """Arm hard-timeout for ``run_id`` (warn → TIMEOUT → grace → force cancel).

        Two-phase warn + hard TIMEOUT notification to the CEO; after TIMEOUT the
        engine bans new LLM/tool calls, grants one wind-down grace round, then
        force-cancels via :meth:`request_cancel` (same cancel_ids channel as
        ``cancel_worker``). Nested drives without a session use the same
        :mod:`timeout_hard` registry.
        """
        if not self.active or run_id in self.completed_run_ids:
            return
        # Register the in-flight worker for cancel_worker short→full resolution
        # (refreshed each dispatch; before the idempotent-arm short-circuit so a
        # re-arm still keeps the registry current). Cleared on disarm / completion.
        self._running_workers[run_id] = role or run_id
        from agentcore.runtime.runs.timeout_hard import (
            HardTimeoutGuard,
            arm_hard_timeout,
            get_hard_timeout,
        )

        existing = get_hard_timeout(run_id)
        if existing is not None and existing._task is not None and not existing._task.done():
            if role:
                existing.role = role or existing.role
            return

        self._worker_started_at[run_id] = time.monotonic()
        self._timeout_notified.discard(run_id)
        self._timeout_warned.discard(run_id)
        self._timeout_wind_down_pending.discard(run_id)
        self._timeout_wind_down_entered.discard(run_id)
        self._timeout_force_cancelled.discard(run_id)

        def _on_warn(guard: HardTimeoutGuard) -> None:
            if not self.active or run_id in self.completed_run_ids:
                return
            self._timeout_warned.add(run_id)
            self._timeout_wind_down_pending.add(run_id)
            logger.info(
                "coordination.worker_timeout_warn",
                run_id=run_id,
                elapsed_s=round(guard.threshold_s * guard.warn_ratio, 1),
                threshold_s=guard.threshold_s,
                warn_ratio=guard.warn_ratio,
                execution_id=self.execution_id,
            )

        def _on_timeout(guard: HardTimeoutGuard) -> None:
            if not self.active or run_id in self.completed_run_ids:
                return
            if run_id in self._timeout_notified:
                return
            self._timeout_notified.add(run_id)
            self._timeout_wind_down_pending.add(run_id)
            started = self._worker_started_at.get(run_id)
            elapsed = (time.monotonic() - started) if started is not None else guard.threshold_s
            status = "cancel_requested" if run_id in self.cancel_ids else "running"
            self.post(
                CoordinationEvent(
                    kind=CoordinationEventKind.TIMEOUT,
                    payload={
                        "run_id": run_id,
                        "role": role or run_id,
                        "elapsed_s": round(elapsed, 1),
                        "threshold_s": guard.threshold_s,
                        "status": status,
                        "hard": True,
                        "reason": (
                            f"队员已运行约 {round(elapsed)}s（阈值 {int(guard.threshold_s)}s），"
                            "仍未交付。执行面已进入硬收尾：禁新调查调用、宽限一轮交卷，"
                            "超宽限将强制取消。可 update_synthesis 先出中间合成，"
                            "或 cancel_worker 立即终止。"
                        ),
                    },
                )
            )
            logger.info(
                "coordination.worker_timeout",
                run_id=run_id,
                elapsed_s=round(elapsed, 1),
                threshold_s=guard.threshold_s,
                execution_id=self.execution_id,
                hard=True,
            )

        def _on_force_cancel(guard: HardTimeoutGuard, reason: str) -> None:
            if run_id in self.completed_run_ids:
                return
            self._timeout_force_cancelled.add(run_id)
            self.request_cancel(run_id)
            logger.info(
                "coordination.worker_timeout_force_cancel",
                run_id=run_id,
                reason=reason,
                execution_id=self.execution_id,
            )

        guard = arm_hard_timeout(
            run_id,
            timeout_s=timeout_s,
            role=role or run_id,
            warn_ratio=None,  # resolved inside arm_hard_timeout from settings
            on_warn=_on_warn,
            on_timeout=_on_timeout,
            on_force_cancel=_on_force_cancel,
            default_timeout_s=DEFAULT_WORKER_TIMEOUT_S,
        )
        # Mirror timer task into legacy map so cancel_all_timeouts / disarm still work.
        if guard is not None and guard._task is not None:
            self._timeout_tasks[run_id] = guard._task

    def consume_timeout_wind_down(self, run_id: str) -> bool:
        """True once when a timeout warn is pending for ``run_id`` (worker loop arms wind-down).

        消费即记入 ``_timeout_wind_down_entered``——这是「该 worker 真正进入过 timeout
        wind-down（工具面据此被收窄）」的唯一权威痕迹，供收尾对账区分真缩水与自然完成。
        """
        from agentcore.runtime.runs.timeout_hard import get_hard_timeout

        guard = get_hard_timeout(run_id)
        if guard is not None and guard.consume_wind_down():
            self._timeout_wind_down_pending.discard(run_id)
            self._timeout_wind_down_entered.add(run_id)
            return True
        if run_id in self._timeout_wind_down_pending:
            self._timeout_wind_down_pending.discard(run_id)
            self._timeout_wind_down_entered.add(run_id)
            return True
        return False

    def was_timeout_notified(self, run_id: str) -> bool:
        """Whether the CEO-facing TIMEOUT notification already fired for ``run_id``."""
        return run_id in self._timeout_notified

    def entered_timeout_wind_down(self, run_id: str) -> bool:
        """Whether ``run_id`` actually consumed a timeout wind-down (tools narrowed).

        仅 :meth:`consume_timeout_wind_down` 被引擎消费后为真；「仅 pending 未消费」
        （worker 在预警窗内自然完成、引擎从未收窄工具面）不算——故超时通知后自然完成不留此痕。
        """
        from agentcore.runtime.runs.timeout_hard import get_hard_timeout

        guard = get_hard_timeout(run_id)
        if guard is not None and guard.wind_down_entered:
            return True
        return run_id in self._timeout_wind_down_entered

    def was_timeout_force_cancelled(self, run_id: str) -> bool:
        """Whether hard-timeout force-cancelled ``run_id`` via cancel_ids."""
        from agentcore.runtime.runs.timeout_hard import get_hard_timeout

        guard = get_hard_timeout(run_id)
        if guard is not None and guard.force_cancel_requested:
            return True
        return run_id in self._timeout_force_cancelled

    def disarm_worker_timeout(self, run_id: str) -> None:
        from agentcore.runtime.runs.timeout_hard import disarm_hard_timeout

        disarm_hard_timeout(run_id)
        self._timeout_tasks.pop(run_id, None)
        self._worker_started_at.pop(run_id, None)
        # Drop from the cancel-resolution registry so a finished worker is no
        # longer resolvable (mark_worker_completed routes through here too).
        self._running_workers.pop(run_id, None)
        self._busy_workers.pop(run_id, None)

    def cancel_all_timeouts(self) -> None:
        for run_id in list(self._timeout_tasks):
            self.disarm_worker_timeout(run_id)
        # Also disarm any registry entries still keyed for this session's workers.
        for run_id in list(self._running_workers):
            self.disarm_worker_timeout(run_id)

    def cancel_run_ids(self) -> frozenset[str]:
        return frozenset(self.cancel_ids)

    def update_draft(self, draft: str) -> None:
        self.draft = draft

    @property
    def budget_remaining(self) -> int:
        """两池合计（向后兼容读法；分池语义见 progress_/decision_budget_remaining）。"""
        return self.progress_budget_remaining + self.decision_budget_remaining

    def consume_progress_budget(self) -> bool:
        """Decrement 进度池 telemetry counter. Always returns True after counting.

        批次 4：池耗尽不再 HOLD 唤醒——调用方仍须唤醒；返回值仅表示「本次是否从正数扣减」。
        """
        if self.progress_budget_remaining <= 0:
            return False
        self.progress_budget_remaining -= 1
        return True

    def consume_decision_budget(self) -> bool:
        """Decrement 决策池 telemetry counter. Returns False when already at floor 0.

        必要决策永不因预算被跳过——调用方仍须唤醒；floor-0 只喂遥测。
        """
        if self.decision_budget_remaining <= 0:
            return False
        self.decision_budget_remaining -= 1
        return True

    def is_necessary_decision(self, events: list[CoordinationEvent]) -> bool:
        """Necessary decision points always wake the CEO (even under budget pressure)."""
        for ev in events:
            if ev.kind is CoordinationEventKind.ALL_COMPLETED:
                return True
            if ev.kind is CoordinationEventKind.DRIVE_CANCELLED:
                return True
            if ev.kind is CoordinationEventKind.ESCALATION:
                return True
            if ev.kind is CoordinationEventKind.USER_INTERJECTION:
                # Boss mid-flight message — always wake; CEO routes in-graph vs queue.
                return True
            if ev.kind is CoordinationEventKind.TIMEOUT and ev.payload.get("run_id"):
                # Per-worker timeout is a decision point; idle-wait nudge (no run_id) is not.
                return True
            if ev.kind is CoordinationEventKind.BOUNDARY_YIELD:
                return True
            if ev.kind is CoordinationEventKind.WORKER_COMPLETED and not self._saw_first_completion:
                return True
        return False

    def stash_interjection(self, interjection_id: str, payload: dict[str, Any]) -> None:
        """Hold enqueue material for ``queue_user_message`` (process-local)."""
        self.pending_interjections[interjection_id] = dict(payload)

    def take_interjection(self, interjection_id: str) -> dict[str, Any] | None:
        return self.pending_interjections.pop(interjection_id, None)

    def get_interjection(self, interjection_id: str) -> dict[str, Any] | None:
        return self.pending_interjections.get(interjection_id)

    def note_decision_points(self, events: list[CoordinationEvent]) -> None:
        for ev in events:
            if ev.kind is CoordinationEventKind.WORKER_COMPLETED:
                self._saw_first_completion = True

    def note_wake(self) -> None:
        """Stamp the last CEO wake time — batching throttles follow-ups from here."""
        self.last_wake_monotonic = time.monotonic()

    def seconds_since_wake(self) -> float | None:
        """Seconds since the last CEO wake, or ``None`` when never woken."""
        if self.last_wake_monotonic is None:
            return None
        return time.monotonic() - self.last_wake_monotonic

    def bump_idle_backoff(self) -> None:
        """One more consecutive idle-patrol timeout (widen the next idle wait)."""
        self.idle_streak += 1

    def reset_idle_backoff(self) -> None:
        """Real team activity arrived — reset the idle-patrol backoff."""
        self.idle_streak = 0

    async def wait_events(
        self,
        *,
        timeout: float | None = None,
        merge_idle: float = 0.05,
    ) -> list[CoordinationEvent]:
        """Wait for at least one event; briefly coalesce follow-ups (cost merge).

        Also consumes ``_pending`` (events drained by ``snapshot`` while this wait
        was blocked). Drain sets ``_wake`` so we do not sit on an empty queue until
        the full timeout.
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        while True:
            if self._pending:
                batch = self._pending
                self._pending = []
                return batch

            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                return []

            # Clear-then-recheck: avoid losing a wake that lands between clear and wait.
            self._wake.clear()
            if self._pending:
                batch = self._pending
                self._pending = []
                return batch

            get_task = asyncio.create_task(self._queue.get())
            wake_task = asyncio.create_task(self._wake.wait())
            done, pending_tasks = await asyncio.wait(
                {get_task, wake_task},
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending_tasks:
                task.cancel()
            for task in pending_tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

            if get_task in done and not get_task.cancelled():
                try:
                    first = get_task.result()
                except (asyncio.CancelledError, Exception):
                    first = None
                if first is not None:
                    batch = [first]
                    if self._pending:
                        batch.extend(self._pending)
                        self._pending = []
                    # Short coalesce window so independent mid-wave completions can merge.
                    coalesce_deadline = loop.time() + merge_idle
                    while True:
                        left = coalesce_deadline - loop.time()
                        if left <= 0:
                            break
                        try:
                            nxt = await asyncio.wait_for(self._queue.get(), timeout=left)
                        except TimeoutError:
                            break
                        batch.append(nxt)
                        if nxt.kind in (
                            CoordinationEventKind.ALL_COMPLETED,
                            CoordinationEventKind.DRIVE_CANCELLED,
                        ):
                            break
                    if self._pending:
                        batch.extend(self._pending)
                        self._pending = []
                    return batch

            # Woken by drain → loop and take ``_pending``. Pure timeout → empty.
            if wake_task not in done and not self._pending:
                return []

    def drain_nowait(self) -> list[CoordinationEvent]:
        batch = list(self._pending)
        self._pending = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    def snapshot(self) -> CoordinationSnapshot:
        pending = [
            {"kind": e.kind.value, "payload": dict(e.payload)}
            for e in (*self._pending, *self._drain_queue_copy())
        ]
        live_plan_json: dict[str, Any] | None = None
        if self.live_plan is not None:
            try:
                from agentcore.runtime.runs.serialize import plan_to_json

                live_plan_json = plan_to_json(self.live_plan)
            except Exception:  # noqa: BLE001 — snapshot must never raise
                logger.warning(
                    "coordination.live_plan_snapshot_failed",
                    execution_id=self.execution_id,
                )
                live_plan_json = None
        interjections = [
            {
                "interjection_id": iid,
                **{k: v for k, v in payload.items() if k in _INTERJECTION_SNAPSHOT_KEYS},
            }
            for iid, payload in self.pending_interjections.items()
        ]
        ownership_dict: dict[str, Any] = {}
        if self.file_ownership is not None:
            try:
                ownership_dict = dict(self.file_ownership.to_dict())
            except Exception:  # noqa: BLE001 — snapshot must never raise
                logger.warning(
                    "coordination.file_ownership_snapshot_failed",
                    execution_id=self.execution_id,
                )
                ownership_dict = {}
        return CoordinationSnapshot(
            execution_id=self.execution_id,
            draft=self.draft,
            conversation_id=self.conversation_id,
            completed_run_ids=sorted(self.completed_run_ids),
            progress_budget_remaining=self.progress_budget_remaining,
            decision_budget_remaining=self.decision_budget_remaining,
            total_workers=self.total_workers,
            active=self.active,
            cancel_run_ids=sorted(self.cancel_ids),
            pending_events=pending,
            pending_arbitrations=[dict(v) for v in self.pending_arbitrations.values()],
            resolved_arbitrations=[dict(v) for v in self.resolved_arbitrations.values()],
            live_plan=live_plan_json,
            pending_interjections=interjections,
            all_completed_injected=self.all_completed_injected,
            harvest_scheduled=self.harvest_scheduled,
            terminal_posted=self.terminal_posted,
            settled_via=self.settled_via,
            turn_attached=self.turn_attached,
            user_stopped=self.user_stopped,
            saw_first_completion=self._saw_first_completion,
            file_ownership=ownership_dict,
        )

    def _drain_queue_copy(self) -> list[CoordinationEvent]:
        """Non-destructive peek is unavailable on Queue — drain into pending + wake."""
        drained: list[CoordinationEvent] = []
        while True:
            try:
                drained.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        self._pending.extend(drained)
        if drained:
            self._wake.set()
        return list(drained)

    @classmethod
    def from_snapshot(cls, snap: CoordinationSnapshot) -> CoordinationSession:
        session = cls(
            execution_id=snap.execution_id,
            total_workers=snap.total_workers,
            progress_budget_remaining=snap.progress_budget_remaining,
            decision_budget_remaining=snap.decision_budget_remaining,
            draft=snap.draft,
            conversation_id=snap.conversation_id,
            completed_run_ids=set(snap.completed_run_ids),
            # Treat restored completions as already reported — avoid re-listing the
            # whole roster as「本轮新完成」on the first post-resume inject.
            progress_reported_completed=set(snap.completed_run_ids),
            cancel_ids=set(snap.cancel_run_ids),
            active=snap.active,
            all_completed_injected=snap.all_completed_injected,
            harvest_scheduled=snap.harvest_scheduled,
            terminal_posted=snap.terminal_posted,
            settled_via=snap.settled_via,
            turn_attached=snap.turn_attached,
            user_stopped=snap.user_stopped,
        )
        if snap.live_plan:
            try:
                from agentcore.runtime.runs.serialize import plan_from_json

                session.live_plan = plan_from_json(snap.live_plan)
            except Exception:  # noqa: BLE001 — tolerate corrupt legacy snapshots
                logger.warning(
                    "coordination.live_plan_restore_failed",
                    execution_id=snap.execution_id,
                )
                session.live_plan = None
        for raw in snap.pending_events:
            kind_raw = str(raw.get("kind") or "")
            try:
                kind = CoordinationEventKind(kind_raw)
            except ValueError:
                continue
            session._pending.append(
                CoordinationEvent(kind=kind, payload=dict(raw.get("payload") or {}))
            )
        for raw in snap.pending_arbitrations:
            rid = str(raw.get("run_id") or "").strip()
            if rid:
                session.pending_arbitrations[rid] = dict(raw)
        for raw in snap.resolved_arbitrations:
            rid = str(raw.get("run_id") or "").strip()
            if rid:
                session.resolved_arbitrations[rid] = dict(raw)
        for raw in snap.pending_interjections:
            iid = str(raw.get("interjection_id") or "").strip()
            if not iid:
                continue
            payload = {k: v for k, v in raw.items() if k in _INTERJECTION_SNAPSHOT_KEYS}
            session.pending_interjections[iid] = payload
        if snap.saw_first_completion or snap.completed_run_ids:
            session._saw_first_completion = True
        if snap.file_ownership:
            from agentcore.workspace.write_claims import WriteCoordinator

            session.file_ownership = WriteCoordinator.from_dict(snap.file_ownership)
        return session

    def close(self) -> None:
        was_active = self.active
        self.active = False
        self.cancel_all_timeouts()
        # 收口：未消化插话升格对话 FIFO（或终局已答 → addressed）。仅从 active→inactive
        # 触发一次，避免重复 close 双入队。
        if was_active and self.pending_interjections:
            from agentcore.runtime.coordination.interjections import (
                promote_pending_on_close,
            )

            promote_pending_on_close(self)


def active_coordination(execution_id: str | None = None) -> CoordinationSession | None:
    """Look up the coordination session for a turn.

    Prefer an explicit ``execution_id`` (tool contexts). When omitted, resolve via
    the turn-entry :data:`current_execution_id` ContextVar (captain wait path).
    ContextVar is a single-task-tree cache only — cross-task callers must pass
    ``execution_id`` or use :func:`active_coordination_for_conversation`.
    """
    eid = (execution_id or "").strip() or (current_execution_id.get() or "").strip()
    if not eid:
        return None
    return _sessions.get(eid)


def adopt_active_execution(
    conversation_id: str,
    *,
    event_sink: Any | None = None,
) -> CoordinationSession | None:
    """Re-attach the conversation's live execution to the calling turn (pillar B).

    Binds :data:`current_execution_id` to the registry session so the CEO wait path
    finds it even when this turn minted a different id. Sets ``turn_attached=True``
    and optionally refreshes ``event_sink``. Returns the adopted session or ``None``.
    """
    session = active_coordination_for_conversation(conversation_id)
    if session is None or not session.active:
        return None
    current_execution_id.set(session.execution_id)
    session.turn_attached = True
    if event_sink is not None:
        session.event_sink = event_sink
    logger.info(
        "coordination.execution_adopted",
        conversation_id=conversation_id,
        execution_id=session.execution_id,
        completed=len(session.completed_run_ids),
        total=session.total_workers,
    )
    return session


def bind_host_journal(
    session: CoordinationSession,
    *,
    writer: Any | None,
    turn_id: str | None = None,
) -> None:
    """Remember the arming turn's journal writer for post-detach DURABLE persistence."""
    if writer is None:
        return
    session.host_journal_writer = writer
    tid = (turn_id or getattr(writer, "turn_id", "") or "").strip()
    if tid:
        session.host_turn_id = tid


def emit_execution_detached(
    session: CoordinationSession,
    *,
    reason: str = "turn_released",
) -> None:
    """Persist + best-effort SSE ``execution_detached`` (pillar D)."""
    from agentcore.runtime.events import execution_detached

    event = execution_detached(
        execution_id=session.execution_id,
        conversation_id=session.conversation_id or "",
        completed=len(session.completed_run_ids),
        total=session.total_workers,
        reason=reason,
        host_turn_id=session.host_turn_id or None,
    )
    sink = session.event_sink
    if sink is not None:
        with contextlib.suppress(Exception):
            sink.emit(event)
    else:
        writer = session.host_journal_writer
        if writer is not None and not getattr(writer, "sealed", False):
            with contextlib.suppress(Exception):
                writer.schedule_append(
                    {
                        "kind": event.type.value,
                        "payload": event.payload,
                        "ts": event.timestamp,
                    }
                )
    logger.info(
        "coordination.execution_detached_emitted",
        execution_id=session.execution_id,
        reason=reason,
        completed=len(session.completed_run_ids),
        total=session.total_workers,
    )


def release_turn_coordination(execution_id: str | None) -> None:
    """Chat-turn teardown: drop idle sessions; preserve live background coordination.

    Coordination lifecycle is decoupled from the chat turn — when a background
    drive is still running (typical cross-turn append / SSE disconnect), detach
    turn ownership and leave the registry entry for the drive's finally to
    harvest+clear. Idle / already-closed sessions are cleared here as before.

    Explicit user /stop is different: :func:`cancel_coordination_on_user_stop`
    marks ``user_stopped`` and cancels the drive; this path then clears instead
    of detaching so workers do not keep running after the turn is closed.
    """
    eid = (execution_id or "").strip()
    if not eid:
        return
    session = _sessions.get(eid)
    if session is None:
        return
    if session.user_stopped:
        # Hard stop already signalled — do not detach for background completion.
        if _drive_live(session):
            # Idempotent: ensure cancel fired even if stop raced ahead of this.
            cancel_coordination_on_user_stop(execution_id=eid)
        if session.active:
            session.close()
        clear_active_coordination(eid)
        logger.info(
            "coordination.user_stop_released",
            execution_id=eid,
            completed=len(session.completed_run_ids),
            total=session.total_workers,
        )
        return
    if _drive_live(session):
        if session.turn_attached:
            emit_execution_detached(session, reason="turn_released")
        session.turn_attached = False
        logger.info(
            "coordination.turn_detached",
            execution_id=eid,
            active=session.active,
            completed=len(session.completed_run_ids),
            total=session.total_workers,
        )
        return
    # Drive finished (or never armed). Safe to drop — same-turn CEO already
    # closed via all_completed inject, or append finished before teardown with
    # nobody left to consume the queue.
    if session.active:
        session.close()
    clear_active_coordination(eid)


def finish_detached_coordination(session: CoordinationSession) -> None:
    """Background drive finally: harvest when unattached; else no-op.

    When the arming turn already ended, schedule the execution harvester (pillar C)
    instead of silently close+unregister — ALL_COMPLETED must reach a consumer.
    """
    if session.turn_attached:
        return
    if session.user_stopped:
        if session.active:
            session.close()
        current = _sessions.get(session.execution_id)
        if current is session:
            clear_active_coordination(session.execution_id)
        return
    if session.harvest_scheduled:
        return
    # No conversation to deliver into (unit tests / orphan sessions): sync clear.
    if not (session.conversation_id or "").strip():
        _close_detached_session(session)
        return
    session.harvest_scheduled = True
    session.mark_settled("harvest")
    # Emit *before* scheduling the async harvest so owners that
    # ``await_live_detached_drive`` still have the turn sink open and can push
    # ``execution_completed`` live (and into outbox before READY). The closing
    # turn itself stays async in ``_run_harvest``.
    from agentcore.runtime.coordination.harvest import emit_execution_completed

    emit_execution_completed(session)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _close_detached_session(session)
        return
    loop.create_task(
        _run_harvest(session),
        name=f"coord-harvest-{session.execution_id[:8]}",
    )


def _close_detached_session(session: CoordinationSession) -> None:
    if session.active:
        session.close()
    current = _sessions.get(session.execution_id)
    if current is session:
        clear_active_coordination(session.execution_id)
        logger.info(
            "coordination.detached_drive_finished",
            execution_id=session.execution_id,
            completed=len(session.completed_run_ids),
            total=session.total_workers,
            settled_via=session.settled_via,
        )


async def _run_harvest(session: CoordinationSession) -> None:
    try:
        from agentcore.runtime.coordination.harvest import harvest_detached_execution

        await harvest_detached_execution(session)
    except Exception:  # noqa: BLE001 — harvest must never leak into drive task
        logger.exception(
            "coordination.harvest_failed",
            execution_id=session.execution_id,
        )
        # Keep registry on unexpected failure so harvest remains observable /
        # re-adoptable — do not silently unregister without a closing turn.


def active_coordination_for_conversation(
    conversation_id: str,
) -> CoordinationSession | None:
    """Live coordination session for ``conversation_id``, or ``None``.

    Used by ``POST …/messages`` to route mid-flight user text into the CEO window
    instead of the conversation-level turn queue.
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return None
    eid = _by_conversation.get(cid)
    if not eid:
        return None
    session = _sessions.get(eid)
    if session is None or not session.active:
        return None
    return session


def set_active_coordination(session: CoordinationSession | None) -> None:
    """Register ``session`` under its ``execution_id``, or clear when ``None``.

    Also binds :data:`current_execution_id` in the *current* context (tests / settle
    in the captain task). When ``set_active`` runs inside an ``asyncio.gather`` child
    (delegate tool), that ContextVar write stays in the child copy — the parent CEO
    loop relies on the turn-entry binding set before gather.

    Mid-coordination secondary ``delegate`` must **merge** into the existing session
    (see :func:`agentcore.runtime.coordination.host.try_start_coordination`) — never
    call this to silently replace an active session for the same ``execution_id``.
    """
    if session is None:
        clear_active_coordination()
        return
    eid = (session.execution_id or "").strip()
    if not eid:
        logger.warning("coordination.set_active_missing_execution_id")
        return
    prior = _sessions.get(eid)
    if (
        prior is not None
        and prior is not session
        and prior.active
        and prior.drive_task is not None
        and not prior.drive_task.done()
    ):
        # Overwrite while a background drive still owns the old session = event
        # crosstalk / lost cancel+arbitration. Callers must merge instead.
        logger.error(
            "coordination.set_active_overwrite_while_live",
            execution_id=eid,
            prior_workers=prior.total_workers,
            new_workers=session.total_workers,
        )
    _sessions[eid] = session
    cid = (session.conversation_id or "").strip()
    if cid:
        _by_conversation[cid] = eid
    current_execution_id.set(eid)


def clear_active_coordination(
    execution_id: str | None = None,
    _token: object | None = None,
) -> None:
    """Drop one session by ``execution_id``, or the whole registry when omitted.

    ``_token`` kept for call-site compat (ignored). Omitting ``execution_id`` clears
    every entry — used by test teardown. Pass an id to isolate concurrent turns.
    """
    eid = (execution_id or "").strip()
    if eid:
        dropped = _sessions.pop(eid, None)
        if dropped is not None:
            dropped.check_terminal_settlement()
            cid = (dropped.conversation_id or "").strip()
            if cid and _by_conversation.get(cid) == eid:
                _by_conversation.pop(cid, None)
        else:
            # Session already gone — still scrub stale conversation index entries.
            stale = [c for c, e in _by_conversation.items() if e == eid]
            for c in stale:
                _by_conversation.pop(c, None)
        return
    for sess in list(_sessions.values()):
        sess.check_terminal_settlement()
    _sessions.clear()
    _by_conversation.clear()


def _drive_live(session: CoordinationSession) -> bool:
    task = session.drive_task
    return task is not None and not task.done()


async def await_live_detached_drive(conversation_id: str) -> bool:
    """Await a live *detached* coordination drive before the sink owner closes.

    Pillar D1 (narrow): after the chat pipeline returns, keep the turn sink open
    until the background drive settles so ``run_completed`` / ``execution_completed``
    still reach the live UI, and so sidecar outbox READY is not sealed while
    post-detach DURABLE journal appends are still in flight.

    No-op (returns False) when there is no live detached drive — user_stop /
    still-attached / idle all close immediately. ``soft_stop`` still awaits a
    live drive so finally-block terminal frames are not dropped by an early
    sink close. Drive-task cancel/failure does not raise; caller cancellation does.
    """
    session = active_coordination_for_conversation(conversation_id)
    if session is None or not session.active:
        return False
    if session.user_stopped or session.turn_attached:
        return False
    task = session.drive_task
    if task is None or task.done():
        return False
    # ``asyncio.wait`` completes when the drive finishes (ok / error / cancel)
    # without re-raising the drive's CancelledError; our own cancellation still
    # propagates so turn cancel paths close the sink immediately.
    await asyncio.wait({task})
    return True


def note_coord_worker_busy(run_id: str, kind: str) -> None:
    """Best-effort stamp: worker ``run_id`` is inside LLM / tool / verify."""
    session = active_coordination()
    if session is None or not session.active:
        return
    session.mark_worker_busy(run_id, kind)


def clear_coord_worker_busy(run_id: str) -> None:
    """Clear the busy stamp for ``run_id`` (end of LLM/tool)."""
    session = active_coordination()
    if session is None:
        return
    session.clear_worker_busy(run_id)


def cancel_coordination_on_user_stop(
    conversation_id: str | None = None,
    *,
    execution_id: str | None = None,
) -> bool:
    """Cascade-cancel live coordination for an explicit user /stop.

    Cancels every in-flight worker (via ``cancel_ids``) and the background
    ``drive_task``. Marks ``user_stopped`` so :func:`release_turn_coordination`
    clears the session instead of detaching. SSE disconnect must NOT call this
    (detach-and-continue semantics stay intact).

    Returns ``True`` when a live session was found and cancelled.
    """
    session: CoordinationSession | None = None
    eid = (execution_id or "").strip()
    if eid:
        session = _sessions.get(eid)
    if session is None:
        cid = (conversation_id or "").strip()
        if cid:
            session = active_coordination_for_conversation(cid)
    if session is None or not session.active:
        return False
    session.user_stopped = True
    running = list(session.running_workers())
    for run_id, _role in running:
        session.request_cancel(run_id)
    task = session.drive_task
    if task is not None and not task.done():
        task.cancel()
    logger.info(
        "coordination.user_stop_cancelled",
        execution_id=session.execution_id,
        conversation_id=session.conversation_id or conversation_id or "",
        cancelled_workers=len(running),
        completed=len(session.completed_run_ids),
        total=session.total_workers,
    )
    return True
