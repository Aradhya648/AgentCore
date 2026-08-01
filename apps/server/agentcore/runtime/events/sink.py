"""EventSink — async queue bridging execution and SSE delivery."""

from __future__ import annotations

import asyncio
import contextlib
import copy
from collections.abc import Callable
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.runtime.events.chat import content_delta
from agentcore.runtime.events.journal_config import (
    _HISTORY_COALESCE_RUN,
    _HISTORY_COALESCE_TURN,
    _HISTORY_SKIP_TYPES,
    _JOURNAL_EVENT_TYPES,
    _JOURNAL_SURFACE_TYPES,
    cap_process_result,
)
from agentcore.runtime.events.process_persist import (
    ProcessPersistCursor,
    should_persist_on_close,
)
from agentcore.runtime.events.stream_checkpointer import StreamCheckpointer
from agentcore.runtime.events.types import EventType, SSEEvent
from agentcore.runtime.facts import Fact, record_turn_fact

# Orchestration tools hand the turn to a sub-team and open a team execution. Their
# captain-level call is NOT rendered as a tool step — the `team` marker (emitted at
# run_plan) stands in its place as the collaboration graph's timeline slot. Mirrors
# the frontend `ORCHESTRATION_TOOLS` (lib/processTimeline.ts); keep the two in lockstep.
# Shared with the conformance oracle (projection.py) so live + golden agree.
ORCHESTRATION_TOOLS = frozenset({"delegate", "debate"})

# CEO self-calls whose inline-timeline slot is stood in for by a DEDICATED marker, so
# they make NO captain tool step: delegate/debate → `team` (at run_plan); ask_user →
# `checkpoint`/`ask` (at *_required / question_posted). Superset of ORCHESTRATION_TOOLS
# (which stays scoped to team/graph semantics). ask_user belongs here because a blocking
# ask SUSPENDs without a tool_use_end (its card marker represents it), and a rejected ask
# (card-shape validation) must not leak a red tool-error row — the model self-corrects and
# re-asks. Mirrors the frontend/mobile fold (processTimeline.ts / fold.ts) + oracle
# (projection.py); keep all in lockstep.
MARKER_STANDIN_TOOLS = ORCHESTRATION_TOOLS | frozenset({"ask_user"})

logger = get_logger(__name__)

# Dev-only observation seam (demo-tape recorder): installed by
# ``agentcore.demo_tape.recorder`` under DEMO_TAPE_RECORD_ENABLED, None otherwise.
# Called for every emitted event AFTER normal processing — purely observational;
# a tap failure is logged and never breaks the turn. Not a product contract.
_emit_tap: Callable[[EventSink, SSEEvent], None] | None = None


def set_emit_tap(tap: Callable[[EventSink, SSEEvent], None] | None) -> None:
    """Install / clear the process-wide emit tap (dev-only, e.g. tape recording)."""
    global _emit_tap
    _emit_tap = tap


def _run_emit_tap(sink: EventSink, event: SSEEvent) -> None:
    if _emit_tap is None:
        return
    try:
        _emit_tap(sink, event)
    except Exception as e:  # noqa: BLE001 — observation must never break the turn
        logger.warning("event_tap.failed", error=str(e))


def _step_has_marker(steps: list[dict[str, Any]], kind: str, key: str, value: str) -> bool:
    return any(s.get("kind") == kind and s.get(key) == value for s in steps)


def _insert_marker_step(
    steps: list[dict[str, Any]],
    marker: dict[str, Any],
    *,
    before_last_team: bool = False,
) -> None:
    """Insert a positional marker into ``steps`` (caller owns dedup).

    ``before_last_team`` mirrors team_preview product narrative: 开工卡 sits just
    before the collaboration-graph ``team`` marker, not after it.
    """
    if before_last_team:
        for i in range(len(steps) - 1, -1, -1):
            if steps[i].get("kind") == "team":
                steps.insert(i, marker)
                return
    steps.append(marker)


def _marker_spec_for_required(
    event_type: EventType | str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool] | None:
    """Build (marker_step, before_last_team) for a timeline-marker surface event.

    Covers ``*_required`` / ask / raised ``run_escalation`` (统一时间线二期). Shared by
    ``EventSink._accumulate_process`` and suspension capture (G7) so live emit and
    ``turn_paused`` snapshot stay lockstep. Returns None when the event is not a
    marker surface or the id is empty.
    """
    t = event_type if isinstance(event_type, EventType) else EventType(event_type)
    if t == EventType.CHECKPOINT_REQUIRED:
        cid = payload.get("checkpoint_id") or ""
        if not cid:
            return None
        return {"kind": "checkpoint", "checkpoint_id": cid}, False
    if t == EventType.QUESTION_POSTED:
        aid = payload.get("ask_id") or ""
        if not aid:
            return None
        return {"kind": "ask", "ask_id": aid}, False
    if t == EventType.PLAN_REVIEW_REQUIRED:
        cid = payload.get("checkpoint_id") or ""
        if not cid:
            return None
        return {"kind": "plan_review", "checkpoint_id": cid}, False
    if t == EventType.TEAM_PREVIEW_REQUIRED:
        cid = payload.get("checkpoint_id") or ""
        if not cid:
            return None
        return {"kind": "team_preview", "checkpoint_id": cid}, True
    if t in (EventType.ESCALATION_REQUIRED, EventType.RUN_ESCALATION):
        eid = payload.get("escalation_id") or ""
        if not eid:
            return None
        return {"kind": "escalation", "escalation_id": eid}, False
    if t == EventType.APPROVAL_REQUIRED:
        aid = payload.get("approval_id") or ""
        if not aid:
            return None
        return {"kind": "approval", "approval_id": aid}, False
    if t == EventType.DELEGATION_AUTHORIZATION_REQUIRED:
        aid = payload.get("authorization_id") or ""
        if not aid:
            return None
        # 产品修正（统一时间线二期落地后拍板）：委派授权与开工卡同属「放行开工」族，
        # 统一叙事 授权 → 团队干活 —— 与 team_preview 同锚定，排协作图 team 标记之前。
        # 仅此一 kind；escalation / approval 维持事件时刻、排图后。
        return {"kind": "delegation_authorization", "authorization_id": aid}, True
    if t == EventType.STAGE_CARD_REQUIRED:
        sid = payload.get("stage_card_id") or ""
        if not sid:
            return None
        return {"kind": "stage_card", "stage_card_id": sid}, False
    return None


def synthesize_required_marker(
    steps: list[dict[str, Any]],
    event_type: EventType | str,
    payload: dict[str, Any],
) -> bool:
    """Synthesize a marker step into ``steps`` from a ``*_required`` event (G7).

    Dedups within ``steps`` (``_has_marker`` semantics on the target list). Returns
    whether a marker was inserted. Capture side uses this on the live process lane
    (then flushes to journal) so the pause-anchor marker lands even though the
    required event emits *after* ``persist_suspension_capture``.
    """
    spec = _marker_spec_for_required(event_type, payload)
    if spec is None:
        return False
    marker, before_last_team = spec
    kind = marker["kind"]
    key = next(k for k in marker if k != "kind")
    value = marker[key]
    if _step_has_marker(steps, kind, key, value):
        return False
    _insert_marker_step(steps, marker, before_last_team=before_last_team)
    return True


class EventSink:
    """Async queue bridging execution (producer) and SSE (consumer)."""

    def __init__(
        self,
        *,
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> None:
        self._queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue()
        self._persist_barriers: asyncio.Queue[asyncio.Future[int | None] | None] = asyncio.Queue()
        self._closed = False
        self._detached = False
        # Strong refs for fire-and-forget barrier combiner tasks so the loop does not
        # destroy them while pending ("Task was destroyed but it is pending").
        self._barrier_tasks: set[asyncio.Task[None]] = set()
        self._history: list[SSEEvent] = []
        self._journal: list[dict[str, Any]] = []
        self._process: list[dict[str, Any]] = []
        # Resume-seeded captain / worker timelines (G1/G7). Deep-copied on seed; never
        # mixed into live ``_process`` / ``_run_processes``. Persist projection merges
        # seeded⊕live; streamed_* and content_reset read/mutate live only.
        self._seeded_process: list[dict[str, Any]] = []
        self._seeded_run_processes: dict[str, list[dict[str, Any]]] = {}
        # Per-worker-run 思考·正文·工具 timeline (对称 CEO ``_process``). Keyed by run_id;
        # tools tagged with ``run_id`` land here (not on the captain bubble). Persisted as
        # ``runs.run_processes`` so reload matches live interleaving — ``message_final``
        # splice is NOT the worker timeline source.
        self._run_processes: dict[str, list[dict[str, Any]]] = {}
        # Progressive process_* / run_process_* journal cursor (ordinal idempotent).
        self._process_cursor = ProcessPersistCursor()
        self._has_run_plan = False
        self._has_tool = False
        self._conversation_id = conversation_id
        self._message_id = message_id
        self._checkpointer: StreamCheckpointer | None = None
        # G6: after content_reset, display-only reinject this text into history + SSE
        # (skip process / checkpointer). None = hook unset (status-quo behaviour).
        self._content_reset_reinjection: str | None = None
        # Soft-fail error (ERROR is history-skipped / not journaled): keep the latest
        # payload so settle can stamp turn_end + result.error for reload.
        self._last_error: dict[str, Any] | None = None
        # MESSAGE_END is DERIVED (history-skipped, never journaled). Capture finish_reason
        # so attach's no-cursor ``take_over`` can synthesize the close frame — same role as
        # ``_turn_end_close_event`` on the journal cursor-replay path (收口窗对齐).
        self._stream_finish_reason: str | None = None
        if conversation_id and message_id:
            self._try_start_stream_checkpointer()

    def bind_content_checkpoint(
        self,
        *,
        conversation_id: str,
        message_id: str,
    ) -> None:
        """Wire stream-segment durability for this turn's assistant row (P1).

        Name kept for call-site stability; the 10s ``messages.content`` checkpoint
        loop is retired in favour of ``StreamCheckpointer`` → ``turn_stream_state``.
        """
        self._conversation_id = conversation_id
        self._message_id = message_id
        self._try_start_stream_checkpointer()

    def _try_start_stream_checkpointer(self) -> None:
        if self._checkpointer is not None or self._closed or not self._message_id:
            return
        self._checkpointer = StreamCheckpointer(turn_id=self._message_id)
        self._checkpointer.start()

    def set_content_reset_reinjection(self, text: str | None) -> None:
        """G6: after each ``content_reset``, display-only reinject ``text`` (or clear hook).

        Resume pipeline sets pre_pause so client bubble reset does not wipe the
        suspended-turn base. Pass ``None`` to disable (status quo).
        """
        self._content_reset_reinjection = text

    @property
    def conversation_id(self) -> str | None:
        """The bound conversation id (None until bind_content_checkpoint / ctor set it)."""
        return self._conversation_id

    @property
    def message_id(self) -> str | None:
        """The bound turn/message id (None until bind_content_checkpoint / ctor set it)."""
        return self._message_id

    def _emit_display_only(self, event: SSEEvent) -> None:
        """History + SSE only — skip process accumulation, journal, and checkpointer."""
        if self._closed:
            return
        self._record_history(event)
        if not self._detached:
            self._queue.put_nowait(event)
            self._persist_barriers.put_nowait(None)
        _run_emit_tap(self, event)

    def emit_sse_only(self, event: SSEEvent) -> None:
        """Public SSE/history path without journal (e.g. interjection confirm stream)."""
        self._emit_display_only(event)

    def _combine_persist_barriers(
        self,
        futures: list[asyncio.Future[int | None] | None],
    ) -> asyncio.Future[int | None] | None:
        """One SSE barrier that awaits every scheduled journal write for this event.

        Process-lane facts must land before (or with) the closing DURABLE so mid-run
        refresh can fold journal alone — invariant: live-visible process ⇒ journal.
        """
        pending = [f for f in futures if f is not None]
        if not pending:
            return None
        if len(pending) == 1:
            return pending[0]
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return pending[-1]
        combined: asyncio.Future[int | None] = loop.create_future()

        async def _wait() -> None:
            seq: int | None = None
            for fut in pending:
                try:
                    allocated = await fut
                except Exception as exc:  # noqa: BLE001 — barrier must not hang SSE
                    if not combined.done():
                        combined.set_exception(exc)
                    return
                if allocated is not None:
                    seq = allocated
            if not combined.done():
                combined.set_result(seq)

        task = loop.create_task(_wait())
        self._barrier_tasks.add(task)
        task.add_done_callback(self._barrier_tasks.discard)
        return combined

    def emit(self, event: SSEEvent) -> None:
        if self._closed:
            # Pillar A: DURABLE display facts persist at execution/host journal scope
            # even after the turn sink closes; SSE / history are best-effort only.
            self._persist_durable_closed(event)
            _run_emit_tap(self, event)
            return
        if event.type is EventType.MESSAGE_END:
            finish = (event.payload or {}).get("finish_reason")
            if finish is not None:
                self._stream_finish_reason = str(finish)
        if event.type is EventType.ERROR:
            self._last_error = dict(event.payload)
        # Accumulate FIRST: closed process_* / run_process_* schedule before the
        # DURABLE fact that closed them (journal interleave == live timeline).
        process_futures = self._accumulate_process(event)
        persist_future: asyncio.Future[int | None] | None = None
        if event.type in _JOURNAL_EVENT_TYPES:
            persist_future = self._schedule_durable_persist(event)
        self._record_history(event)
        if self._checkpointer is not None:
            self._checkpointer.observe(event)
        if not self._detached:
            self._queue.put_nowait(event)
            self._persist_barriers.put_nowait(
                self._combine_persist_barriers([*process_futures, persist_future])
            )
        _run_emit_tap(self, event)
        # G6: reinject after content_reset is fully processed (history + SSE +
        # checkpointer already saw the reset). Display-only path skips process /
        # checkpointer so salvage and persist timelines stay unduplicated.
        if (
            event.type is EventType.CONTENT_RESET
            and self._content_reset_reinjection is not None
        ):
            self._emit_display_only(content_delta(self._content_reset_reinjection))

    def _persist_durable_closed(self, event: SSEEvent) -> None:
        """Journal-only path after sink.close — no history / SSE / process lane."""
        if event.type not in _JOURNAL_EVENT_TYPES:
            return
        self._schedule_durable_persist(event)

    def _schedule_durable_persist(
        self, event: SSEEvent
    ) -> asyncio.Future[int | None] | None:
        """Append a DURABLE fact to the host/execution journal (sink-lifetime independent)."""
        from agentcore.runtime.delegate.graph_append import (
            current_graph_append_redirect,
            is_graph_growth_event,
            register_graph_host,
        )
        from agentcore.runtime.journal.writer import current_journal_writer

        redirect = current_graph_append_redirect.get()
        divert = redirect is not None and is_graph_growth_event(
            event.type, dict(event.payload or {})
        )
        if divert and redirect is not None:
            # 跨回合同图追加：生长帧续写宿主 turn_id，不落追加回合 journal。
            return redirect.host_writer.schedule_append(
                {
                    "kind": event.type.value,
                    "payload": event.payload,
                    "ts": event.timestamp,
                }
            )
        if event.type is EventType.RUN_PLAN and self._message_id:
            register_graph_host(
                str(event.payload.get("execution_id") or ""),
                self._message_id,
            )
        self._journal.append(
            {
                "type": event.type.value,
                "payload": event.payload,
                "timestamp": event.timestamp,
            }
        )
        # Prefer turn ContextVar writer (also updates fact_log) while the arming
        # turn is still attached. After ContextVar reset *or* detach
        # (``turn_attached=False``), DURABLE ``run_*`` / ``execution_*`` must land
        # on the execution-bound host writer — child tasks may still see a stale
        # ContextVar pointing at a sealed/new-turn writer.
        host_writer = self._execution_host_writer(event)
        detached = self._coordination_detached(event)
        if current_journal_writer.get() is not None and not detached:
            return record_turn_fact(
                Fact(
                    kind=event.type.value,
                    payload=event.payload,
                    ts=event.timestamp,
                )
            )
        if host_writer is not None:
            return host_writer.schedule_append(
                {
                    "kind": event.type.value,
                    "payload": event.payload,
                    "ts": event.timestamp,
                }
            )
        return record_turn_fact(
            Fact(
                kind=event.type.value,
                payload=event.payload,
                ts=event.timestamp,
            )
        )

    def _execution_host_writer(self, event: SSEEvent):
        """Bound host journal writer for the event's execution, if any.

        Resolve order: payload.execution_id → current_execution_id ContextVar →
        conversation registry (cross-task after turn teardown resets ContextVars).
        """
        session = self._coordination_session_for_event(event)
        if session is None:
            return None
        writer = getattr(session, "host_journal_writer", None)
        if writer is None or getattr(writer, "sealed", False):
            return None
        return writer

    def _coordination_session_for_event(self, event: SSEEvent):
        """Live coordination session for ``event``, if any."""
        from agentcore.runtime.coordination.session import (
            active_coordination,
            active_coordination_for_conversation,
        )

        eid = str((event.payload or {}).get("execution_id") or "").strip()
        session = active_coordination(eid) if eid else active_coordination()
        if session is None and self._conversation_id:
            session = active_coordination_for_conversation(self._conversation_id)
        return session

    def _coordination_detached(self, event: SSEEvent) -> bool:
        """True when the event's coordination session has released the arming turn."""
        session = self._coordination_session_for_event(event)
        return session is not None and not session.turn_attached

    def _record_history(self, event: SSEEvent) -> None:
        t = event.type
        if t in _HISTORY_SKIP_TYPES:
            return
        if t in _HISTORY_COALESCE_TURN:
            delta = event.payload.get("delta") or ""
            if not delta:
                return
            last = self._history[-1] if self._history else None
            if last is not None and last.type == t:
                last.payload["delta"] = (last.payload.get("delta") or "") + delta
            else:
                self._history.append(
                    SSEEvent(type=t, payload={"delta": delta}, timestamp=event.timestamp)
                )
            return
        if t in _HISTORY_COALESCE_RUN:
            delta = event.payload.get("delta") or ""
            if not delta:
                return
            run_id = event.payload.get("run_id")
            last = self._history[-1] if self._history else None
            if last is not None and last.type == t and last.payload.get("run_id") == run_id:
                last.payload["delta"] = (last.payload.get("delta") or "") + delta
            else:
                self._history.append(
                    SSEEvent(type=t, payload=dict(event.payload), timestamp=event.timestamp)
                )
            return
        if t == EventType.TOOL_USE_END:
            payload = dict(event.payload)
            payload["result"] = cap_process_result(payload.get("result"))
            self._history.append(SSEEvent(type=t, payload=payload, timestamp=event.timestamp))
            return
        self._history.append(SSEEvent(type=t, payload=event.payload, timestamp=event.timestamp))

    def detach(self) -> None:
        self._detached = True

    def take_over(self) -> list[SSEEvent]:
        while True:
            try:
                self._queue.get_nowait()
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._persist_barriers.get_nowait()
            except asyncio.QueueEmpty:
                break
        snapshot = list(self._history)
        # Align with journal cursor replay: MESSAGE_END is history-skipped, and a
        # detached turn emits it while nobody is attached — without a synthetic close
        # the client finalizes only via reconnect-banner salvage (bubble stuck streaming).
        if self._stream_finish_reason is not None:
            snapshot.append(
                SSEEvent(
                    type=EventType.MESSAGE_END,
                    payload={"finish_reason": self._stream_finish_reason},
                )
            )
        if self._closed:
            self._queue.put_nowait(None)
            self._persist_barriers.put_nowait(None)
        else:
            self._detached = False
        return snapshot

    def _has_marker(self, kind: str, key: str, value: str) -> bool:
        """Whether a positional marker step (team / checkpoint / ask / plan_review) for
        ``value`` is already in the timeline — keeps a replayed / multi-batch event from
        dropping a duplicate anchor. Scans seeded ⊕ live so resume-seeded anchors dedup."""
        return _step_has_marker(self._seeded_process, kind, key, value) or _step_has_marker(
            self._process, kind, key, value
        )

    def _run_process(self, run_id: str) -> list[dict[str, Any]]:
        return self._run_processes.setdefault(run_id, [])

    def _persist_closed_captain_text(self) -> list[Any]:
        """Journal the open captain text step that a boundary is about to close."""
        merged = self.raw_process()
        if not merged or not should_persist_on_close(merged[-1]):
            return []
        return self._process_cursor.persist_captain_range(merged, start=0, end=len(merged))

    def _persist_closed_run_text(self, run_id: str) -> list[Any]:
        steps = self._run_process(run_id)
        seeded = self._seeded_run_processes.get(run_id) or []
        merged = [*seeded, *steps] if seeded else list(steps)
        if not merged or not should_persist_on_close(merged[-1]):
            return []
        return self._process_cursor.persist_run_range(run_id, merged, start=0, end=len(merged))

    def flush_process_to_journal(self) -> None:
        """Persist every not-yet-journaled process / run_process step (finalize / pause).

        Call at semantic turn boundaries so open trailing text steps and markers land
        before ``turn_end`` / ``turn_paused``. Idempotent via the ordinal cursor.
        """
        self._process_cursor.persist_new_captain_tail(self.raw_process())
        for rid, steps in self._merged_run_processes().items():
            self._process_cursor.persist_new_run_tail(rid, steps)

    def _persist_captain_marker_after_insert(
        self,
        marker: dict[str, Any],
        *,
        before_last_team: bool,
    ) -> list[Any]:
        """Journal a newly inserted captain marker (append or ``before_last_team``).

        Ordinal tail persist covers the common append case. Two compensations:

        - Mid-insert behind the cursor (``team`` already journaled at ``run_plan``,
          then 开工卡 / 授权 inserts before it): schedule the marker alone and advance
          the cursor by one so the shifted tail is not re-journaled.
        - Open tool ahead of the marker holds the cursor (SUSPEND ``ask_user``): schedule
          the marker and seed past the lane.
        """
        from agentcore.runtime.events.process_persist import schedule_process_step

        merged = self.raw_process()
        kind = marker["kind"]
        key = next(k for k in marker if k != "kind")
        marker_idx = next(
            (
                i
                for i, step in enumerate(merged)
                if step.get("kind") == kind and step.get(key) == marker[key]
            ),
            None,
        )
        futures: list[Any] = []
        if (
            before_last_team
            and marker_idx is not None
            and marker_idx < self._process_cursor.captain
        ):
            fut = schedule_process_step(marker)
            if fut is not None:
                futures.append(fut)
            self._process_cursor.seed_captain(self._process_cursor.captain + 1)
        futures.extend(self._process_cursor.persist_new_captain_tail(merged))
        # Open tool ahead of the marker holds the ordinal cursor — compensate.
        if marker_idx is not None and self._process_cursor.captain <= marker_idx:
            fut = schedule_process_step(marker)
            if fut is not None:
                futures.append(fut)
            self._process_cursor.seed_captain(len(merged))
        return futures

    def persist_required_marker(self, event_type: Any, payload: dict[str, Any]) -> None:
        """Insert a pause-anchor marker into the live captain lane and journal it.

        The ``*_required`` SSE is emitted *after* suspension capture, so the capture
        path must synthesize the marker itself for process_* progressive persistence.

        Mirrors the live SSE ``*_required`` accumulate path (close open text → insert
        → ordinal tail persist) so ``before_last_team`` markers keep live order in
        ``process_*`` (开工卡 before ``team``). When an open tool ahead of the marker
        holds the cursor (SUSPEND ``ask_user`` never emits ``tool_use_end`` before
        pause), fall back to scheduling the marker fact + seeding the cursor past
        the lane — same compensation the old always-``seed_captain(len)`` path used,
        but only when ordinal persist could not reach the marker.
        """
        spec = _marker_spec_for_required(event_type, payload)
        if spec is None:
            return
        marker, before_last_team = spec
        kind = marker["kind"]
        key = next(k for k in marker if k != "kind")
        if self._has_marker(kind, key, marker[key]):
            return

        # before_last_team: insert BEFORE closing/persisting so a trailing text step
        # cannot pin ``team`` ahead of the marker in process_* order. Append markers
        # still close open text first (live SSE parity).
        if not before_last_team:
            self._persist_closed_captain_text()
        if not synthesize_required_marker(self._process, event_type, payload):
            return

        self._persist_captain_marker_after_insert(
            marker, before_last_team=before_last_team
        )

    def _accumulate_run_process(self, event: SSEEvent) -> list[Any]:
        """Accumulate a worker run's ProcessStep[] (mirrors captain ``_accumulate_process``)."""
        futures: list[Any] = []
        t = event.type
        payload = event.payload
        if t == EventType.RUN_REASONING_DELTA:
            run_id = payload.get("run_id") or ""
            delta = payload.get("delta") or ""
            if not run_id or not delta:
                return futures
            steps = self._run_process(run_id)
            if steps and steps[-1].get("kind") == "reasoning":
                steps[-1]["text"] += delta
            else:
                if steps and should_persist_on_close(steps[-1]):
                    futures.extend(self._persist_closed_run_text(run_id))
                steps.append({"kind": "reasoning", "text": delta})
        elif t == EventType.RUN_OUTPUT_DELTA:
            run_id = payload.get("run_id") or ""
            delta = payload.get("delta") or ""
            if not run_id or not delta:
                return futures
            steps = self._run_process(run_id)
            if steps and steps[-1].get("kind") == "content":
                steps[-1]["text"] += delta
            else:
                if steps and should_persist_on_close(steps[-1]):
                    futures.extend(self._persist_closed_run_text(run_id))
                steps.append({"kind": "content", "text": delta})
        elif t == EventType.RUN_OUTPUT_RESET:
            run_id = payload.get("run_id") or ""
            if not run_id:
                return futures
            steps = self._run_process(run_id)
            # Discard open (unpersisted) trailing content — do not journal it.
            while steps and steps[-1].get("kind") == "content":
                steps.pop()
            # Only 交付前核验回炉 leaves the persisted「已按交付规范重写」trace; every
            # other reason (retry / narration / …) clears the draft without a chip.
            if payload.get("reason") == "finish_guard":
                steps.append({"kind": "rework"})
                seeded = self._seeded_run_processes.get(run_id) or []
                merged = [*seeded, *steps] if seeded else list(steps)
                futures.extend(self._process_cursor.persist_new_run_tail(run_id, merged))
        elif t == EventType.TOOL_USE_START:
            run_id = payload.get("run_id") or ""
            if not run_id:
                return futures
            futures.extend(self._persist_closed_run_text(run_id))
            self._run_process(run_id).append(
                {
                    "kind": "tool",
                    "id": payload.get("tool_call_id", ""),
                    "tool_name": payload.get("tool_name", ""),
                    "arguments": payload.get("arguments") or {},
                    "result": None,
                    "status": "running",
                }
            )
        elif t == EventType.TOOL_USE_END:
            run_id = payload.get("run_id") or ""
            if not run_id:
                return futures
            call_id = payload.get("tool_call_id", "")
            result = cap_process_result(payload.get("result"))
            display = payload.get("display")
            for step in reversed(self._run_process(run_id)):
                if step.get("kind") == "tool" and step.get("id") == call_id:
                    step["result"] = result
                    step["status"] = payload.get("status", "success")
                    if display is not None:
                        step["display"] = display
                    break
            seeded = self._seeded_run_processes.get(run_id) or []
            live = self._run_process(run_id)
            merged = [*seeded, *live] if seeded else list(live)
            # Terminal tool persist (holds open tools on flush; compensates if cursor
            # already advanced past a stale running row).
            futures.extend(
                self._process_cursor.persist_resolved_run_tool(run_id, merged, call_id)
            )
        return futures

    def _accumulate_process(self, event: SSEEvent) -> list[Any]:
        # Worker-scoped deltas / tools accumulate on the per-run lane first (then the
        # captain branch no-ops them via run_id / event-type guards below).
        futures = self._accumulate_run_process(event)
        t = event.type
        if t == EventType.RUN_PLAN:
            self._has_run_plan = True
            # 跨回合同图追加：带 host_message_id 的生长 run_plan 不在新回合插 team 标记
            # （锚点由 graph_append 承担；宿主回合已有 team 标记）。
            if event.payload.get("host_message_id"):
                return futures
            # 协作图时间线落点 (统一团队时间线): the FIRST run_plan of an execution drops a
            # zero-width `team` marker at its chronological spot, so the inline graph renders
            # there rather than at the bottom. Later batches (same execution_id) merge into the
            # same graph — one marker per execution.
            execution_id = event.payload.get("execution_id") or ""
            if execution_id and not self._has_marker("team", "execution_id", execution_id):
                futures.extend(self._persist_closed_captain_text())
                self._process.append({"kind": "team", "execution_id": execution_id})
                # Same as other timeline markers: journal at insert so mid-run reload
                # (workers still running, no captain flush yet) replays ``team``.
                futures.extend(
                    self._process_cursor.persist_new_captain_tail(self.raw_process())
                )
        elif t == EventType.GRAPH_APPEND:
            futures.extend(self._persist_closed_captain_text())
            self._process.append(
                {
                    "kind": "graph_append",
                    "execution_id": event.payload.get("execution_id") or "",
                    "host_message_id": event.payload.get("host_message_id") or "",
                    "added_count": int(event.payload.get("added_count") or 0),
                }
            )
        elif t == EventType.REASONING_DELTA:
            delta = event.payload.get("delta") or ""
            if not delta:
                return futures
            if self._process and self._process[-1].get("kind") == "reasoning":
                self._process[-1]["text"] += delta
            else:
                if self._process and should_persist_on_close(self._process[-1]):
                    futures.extend(self._persist_closed_captain_text())
                self._process.append({"kind": "reasoning", "text": delta})
        elif t == EventType.CONTENT_DELTA:
            delta = event.payload.get("delta") or ""
            if not delta:
                return futures
            if self._process and self._process[-1].get("kind") == "content":
                self._process[-1]["text"] += delta
            else:
                if self._process and should_persist_on_close(self._process[-1]):
                    futures.extend(self._persist_closed_captain_text())
                self._process.append({"kind": "content", "text": delta})
        elif t == EventType.CONTENT_RESET:
            # Discard open (unpersisted) trailing content — do not journal discarded prose.
            while self._process and self._process[-1].get("kind") == "content":
                self._process.pop()
        elif t == EventType.TOOL_USE_START:
            payload = event.payload
            # Skip a delegated worker's call (run-scoped — belongs to its run node, not the
            # captain timeline) and a marker-standin call (delegate/debate → `team`;
            # ask_user → `checkpoint`/`ask`). Neither becomes a captain tool step.
            if payload.get("run_id") or payload.get("tool_name") in MARKER_STANDIN_TOOLS:
                return futures
            futures.extend(self._persist_closed_captain_text())
            self._has_tool = True
            self._process.append(
                {
                    "kind": "tool",
                    "id": payload.get("tool_call_id", ""),
                    "tool_name": payload.get("tool_name", ""),
                    "arguments": payload.get("arguments") or {},
                    "result": None,
                    "status": "running",
                }
            )
        elif t == EventType.TOOL_USE_END:
            payload = event.payload
            if payload.get("run_id") or payload.get("tool_name") in MARKER_STANDIN_TOOLS:
                return futures
            call_id = payload.get("tool_call_id", "")
            result = cap_process_result(payload.get("result"))
            display = payload.get("display")
            for step in reversed(self._process):
                if step.get("kind") == "tool" and step.get("id") == call_id:
                    step["result"] = result
                    step["status"] = payload.get("status", "success")
                    if display is not None:
                        step["display"] = display
                    break
            # Terminal tool persist (holds open tools on flush; compensates if cursor
            # already advanced past a stale running row).
            futures.extend(
                self._process_cursor.persist_resolved_captain_tool(
                    self.raw_process(), call_id
                )
            )
        elif t in (
            EventType.CHECKPOINT_REQUIRED,
            EventType.QUESTION_POSTED,
            EventType.PLAN_REVIEW_REQUIRED,
            EventType.TEAM_PREVIEW_REQUIRED,
            EventType.ESCALATION_REQUIRED,
            EventType.RUN_ESCALATION,
            EventType.APPROVAL_REQUIRED,
            EventType.DELEGATION_AUTHORIZATION_REQUIRED,
            EventType.STAGE_CARD_REQUIRED,
        ):
            # Positional card / 痕迹 anchors — shared builder with synthesize_required_marker
            # (G7). Dedup scans seeded⊕live; insert targets live only.
            spec = _marker_spec_for_required(t, event.payload)
            if spec is None:
                return futures
            marker, before_last_team = spec
            kind = marker["kind"]
            key = next(k for k in marker if k != "kind")
            if self._has_marker(kind, key, marker[key]):
                return futures
            futures.extend(self._persist_closed_captain_text())
            _insert_marker_step(self._process, marker, before_last_team=before_last_team)
            # Middle-insert (before_last_team) after an already-journaled ``team`` needs
            # cursor compensation — shared with persist_required_marker.
            futures.extend(
                self._persist_captain_marker_after_insert(
                    marker, before_last_team=before_last_team
                )
            )
        return futures

    def seed_journal(self, events: list[dict[str, Any]]) -> None:
        self._journal.extend(events)

    def seed_process(self, steps: list[dict[str, Any]]) -> None:
        """Hydrate resume captain timeline into the seeded zone (G1/G7). Deep-copied."""
        self._seeded_process = copy.deepcopy(list(steps))
        # Seeded steps already lived in journal — skip re-append on flush.
        self._process_cursor.seed_captain(len(self._seeded_process))

    def seed_run_processes(self, run_map: dict[str, list[dict[str, Any]]]) -> None:
        """Hydrate resume worker timelines into the seeded zone (G1/G7). Deep-copied."""
        self._seeded_run_processes = {
            rid: copy.deepcopy(list(steps)) for rid, steps in run_map.items()
        }
        for rid, steps in self._seeded_run_processes.items():
            self._process_cursor.seed_run(rid, len(steps))

    def raw_process(self) -> list[dict[str, Any]]:
        """Seeded ⊕ live captain steps with **no** structural gate (G1 capture).

        Unlike ``process_timeline()``, a pure prose turn still returns its steps —
        suspension snapshots must not drop pre-pause content/reasoning.
        """
        if not self._seeded_process:
            return list(self._process)
        return [*self._seeded_process, *self._process]

    def raw_run_processes(self) -> dict[str, list[dict[str, Any]]]:
        """Seeded ⊕ live worker step maps with **no** empty-map gate (G1 capture)."""
        return self._merged_run_processes()

    def _merged_run_processes(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for rid, steps in self._seeded_run_processes.items():
            if steps:
                out[rid] = list(steps)
        for rid, steps in self._run_processes.items():
            if not steps:
                continue
            prior = out.get(rid)
            out[rid] = [*prior, *steps] if prior else list(steps)
        return out

    def execution_journal(self) -> list[dict[str, Any]] | None:
        has_surface = any(e["type"] in _JOURNAL_SURFACE_TYPES for e in self._journal)
        return self._journal if has_surface else None

    def process_timeline(self) -> list[dict[str, Any]] | None:
        # Persist the timeline whenever it carries STRUCTURE beyond the CEO's own text —
        # a tool, the team graph, or an interaction / 痕迹 marker (checkpoint / ask /
        # plan_review / team_preview / escalation / approval / delegation_authorization).
        # A pure reasoning/content turn needs none (the content scalar IS the answer, and
        # reasoning rides its own column), matching the fold's "tool-less single-agent turn
        # → no process" so live / reload / golden stay aligned.
        # Gate scans seeded⊕live; unseeded path returns the live list by reference
        # (status-quo identity for callers that mutate / compare).
        if self._seeded_process:
            merged = [*self._seeded_process, *self._process]
            structural = any(s.get("kind") not in ("reasoning", "content") for s in merged)
            return merged if structural else None
        structural = any(s.get("kind") not in ("reasoning", "content") for s in self._process)
        return self._process if structural else None

    def run_process_timelines(self) -> dict[str, list[dict[str, Any]]] | None:
        """Per-run ProcessStep[] maps for worker detail timelines (对称 CEO process).

        Persist any non-empty run timeline so reload keeps true interleaving (tools
        between thinking/output). Empty map → None (no field on the runs payload).
        When seeded, returns seeded⊕live merge; otherwise the live map only (status quo).
        """
        if self._seeded_run_processes:
            out = self._merged_run_processes()
            return out or None
        out = {rid: steps for rid, steps in self._run_processes.items() if steps}
        return out or None

    def last_turn_error(self) -> dict[str, Any] | None:
        """Latest ``error`` SSE payload (code/message[/context]), or None.

        ERROR events are transport-only (not journaled / not in ``_history``); this
        is the durable hand-off into ``turn_end`` + settle result for reload.
        """
        return self._last_error

    def streamed_content(self) -> str:
        """The CEO bubble's currently-streamed text — concatenated ``content``-kind
        process entries, honoring ``content_reset`` (reset pops them).

        断线别白干 (中途取消 salvage): the partial reply the user already saw, read off the
        turn's live accumulation so a turn CANCELLED before it persisted keeps that text
        instead of being replaced by a generic「连接中断」note. Empty for a turn that had
        streamed no assistant text yet (e.g. still mid-tool). Accumulates even while
        detached, so a disconnect that later cancels still recovers what streamed.

        Live zone only — seeded pre-pause content must not re-enter salvage joins (G8).
        """
        return "".join(
            step.get("text", "") for step in self._process if step.get("kind") == "content"
        )

    def streamed_reasoning(self) -> str:
        """CEO thinking text accumulated so far (live ``reasoning`` steps only)."""
        return "".join(
            step.get("text", "") for step in self._process if step.get("kind") == "reasoning"
        )

    def stream_memory_snapshot(self) -> dict[str, str]:
        """In-memory stream-channel texts (for error/FAILED salvage merge)."""
        if self._checkpointer is None:
            return {}
        return self._checkpointer.memory_snapshot()

    async def flush_stream_state(self) -> None:
        """Best-effort flush of dirty stream segments (call before turn收口)."""
        if self._checkpointer is not None:
            await self._checkpointer.flush()

    def captain_context(self) -> list[dict[str, Any]] | None:
        from agentcore.runtime.runs.types import RunKind

        captain_run_id: str | None = None
        for e in self._journal:
            payload = e.get("payload") or {}
            if (
                e.get("type") == EventType.RUN_STARTED.value
                and payload.get("kind") == RunKind.CAPTAIN.value
            ):
                captain_run_id = payload.get("run_id")
                break
        if captain_run_id is None:
            return None
        found = False
        blocks: list[dict[str, Any]] = []
        for e in self._journal:
            payload = e.get("payload") or {}
            if (
                e.get("type") == EventType.RUN_CONTEXT.value
                and payload.get("run_id") == captain_run_id
            ):
                found = True
                blocks.extend(payload.get("blocks") or [])
        return blocks if found else None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            for task in list(self._barrier_tasks):
                task.cancel()
            self._barrier_tasks.clear()
            if self._checkpointer is not None:
                # Schedule final flush without blocking close (SSE consumer may still drain).
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._checkpointer.close())
                except RuntimeError:
                    pass
                self._checkpointer = None
            self._queue.put_nowait(None)
            self._persist_barriers.put_nowait(None)

    async def get(self) -> SSEEvent | None:
        event = await self._queue.get()
        if event is None:
            return None
        barrier = await self._persist_barriers.get()
        if barrier is not None:
            allocated = await barrier
            if allocated is not None:
                event.seq = allocated
        return event

    async def __aiter__(self):
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event
