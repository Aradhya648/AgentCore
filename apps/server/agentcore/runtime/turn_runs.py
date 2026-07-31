"""In-process registry of active chat-turn runs (执行与请求解耦 C1 · slice 1a).

Background — why this exists
---------------------------
A chat turn used to be bound to its SSE request: the route spawned the pipeline as
a ``producer`` task and the SSE layer cancelled it the instant the client
disconnected. That coupling lost the most painful real case (实测案例复盘 案例 1: a
7-minute 法律论文 turn dropped its connection and the whole delivery was thrown
away). To decouple execution from the request, the turn now runs as a *detached*
task tracked here, keyed by ``conversation_id``; the SSE layer only ATTACHES to it.

Resulting lifecycle
-------------------
- **client disconnect** → the SSE stream detaches, but the run keeps going and
  persists its reply in the background (断线不再丢交付).
- **explicit stop** (``POST .../stop``) → :meth:`stop` cancels the run task, which
  unwinds through the turn's existing ``CancelledError`` salvage (finished team
  work is kept as an incomplete message).
- **lifespan shutdown** → :func:`salvage_turns_on_shutdown` marks clean-cancel,
  cascade-stops every live run, awaits unwind (grace timeout), then force-releases
  leftover leases — never the sweeper orphan path.
- **normal completion** → the task's done-callback drops it from the registry.

Posture
-------
This registry is the **process-local cache** of live tasks + sinks. Durable RUNNING
ownership lives in ``turn_leases`` (Postgres; heartbeat + owner) so a process restart
no longer silently drops in-flight turns — the lease sweeper claims expired rows and
routes them through ``recover_turn``. Reconnect (``EventSink.take_over`` / ``detach``)
and stop stay orthogonal to recover. Cross-process Redis lease backend is a later
swap behind the same repository seam.
"""

import asyncio
import contextlib
from dataclasses import dataclass

from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.runtime.events import EventSink

logger = get_logger(__name__)


@dataclass
class TurnRun:
    """A detached chat-turn task and its sink, tracked while it runs."""

    run_id: str
    conversation_id: str
    task: asyncio.Task
    sink: EventSink
    # Set by :meth:`stop` / :meth:`stop_and_drain` / shutdown salvage before
    # ``task.cancel()`` so the CancelledError handler can tell clean cancel
    # (terminal + release) from true hard kill (orphan lease for sweeper).
    user_stopped: bool = False


# Set on an ``asyncio.Task`` when that specific run was cancelled by user stop /
# overlap supersede — survives slot replacement so the old task's CancelledError
# salvage still sees :meth:`is_user_stop` as True.
_TASK_USER_STOPPED = "_agentcore_user_stopped"

# Lifespan finally: graceful shutdown salvage (interrupt + release, never orphan).
# True hard kill / crash without lifespan still orphans for the sweeper.
_shutting_down: bool = False


class TurnRunRegistry:
    """Tracks the active detached run per conversation (one active run each).

    Turns for one conversation are serialized client-side and by the folder-level
    ``workspace_lock``, so one active run per ``conversation_id`` is the model. A
    rare overlap (e.g. a regenerate fired before the prior run cleared) cancels the
    older task (marked user-stopped) before the newer run takes the slot — otherwise
    the orphaned task can no longer be addressed by :meth:`stop`.
    """

    def __init__(self) -> None:
        self._runs: dict[str, TurnRun] = {}

    @staticmethod
    def _mark_user_stopped(run: TurnRun) -> None:
        run.user_stopped = True
        setattr(run.task, _TASK_USER_STOPPED, True)

    @staticmethod
    def begin_shutdown_salvage() -> None:
        """Arm process-wide shutdown salvage before cancelling live turns."""
        global _shutting_down
        _shutting_down = True

    @staticmethod
    def end_shutdown_salvage() -> None:
        """Clear the shutdown flag (tests / re-entry)."""
        global _shutting_down
        _shutting_down = False

    @staticmethod
    def is_shutdown_salvage() -> bool:
        """True while lifespan is salvaging in-flight turns."""
        return _shutting_down

    def register(self, *, conversation_id: str, task: asyncio.Task, sink: EventSink) -> str:
        """Track ``task`` as the conversation's active run; returns its ``run_id``.

        Installs a done-callback that drops the run from the registry when it ends —
        only if it is still the registered one, so a newer run is never evicted by an
        older task finishing. An in-flight prior run is cancelled (user-stop salvage)
        so overlap cannot leave an unstoppable orphan.
        """
        run_id = new_id()
        existing = self._runs.get(conversation_id)
        if existing is not None and not existing.task.done():
            logger.warning(
                "turn_run.overlap",
                conversation_id=conversation_id,
                existing_run_id=existing.run_id,
                new_run_id=run_id,
            )
            self._mark_user_stopped(existing)
            with contextlib.suppress(Exception):
                from agentcore.runtime.coordination.session import (
                    cancel_coordination_on_user_stop,
                )

                cancel_coordination_on_user_stop(conversation_id)
            existing.task.cancel()
        self._runs[conversation_id] = TurnRun(
            run_id=run_id,
            conversation_id=conversation_id,
            task=task,
            sink=sink,
        )
        task.add_done_callback(lambda _t: self._discard(conversation_id, run_id))
        return run_id

    def _discard(self, conversation_id: str, run_id: str) -> None:
        current = self._runs.get(conversation_id)
        if current is not None and current.run_id == run_id:
            del self._runs[conversation_id]
            # Explicit serialisation: start the next queued user message, if any.
            try:
                from agentcore.runtime.turn_queue import turn_queue

                turn_queue.schedule_drain(conversation_id)
            except Exception:  # noqa: BLE001 — queue drain must not break done-callback
                logger.exception(
                    "turn_run.queue_drain_failed",
                    conversation_id=conversation_id,
                )

    def get(self, conversation_id: str) -> TurnRun | None:
        """The conversation's active run, or ``None`` if nothing is running."""
        return self._runs.get(conversation_id)

    def stop(self, conversation_id: str) -> bool:
        """Hard-cancel the conversation's active run (explicit ``POST .../stop``).

        Returns ``True`` if a live run was found and signalled, ``False`` when
        nothing is running (already finished / never started) — so the endpoint is
        idempotent. Cancelling drives the turn through its ``CancelledError`` salvage
        (finished work kept as an incomplete message), then the done-callback clears
        the slot.

        Marks ``user_stopped`` before cancel so lease handling releases (terminal)
        instead of orphaning for sweeper reclaim. Also cascade-cancels any live
        coordination drive + in-flight workers (SSE disconnect must NOT use this
        path — detach-and-continue stays on ``release_turn_coordination`` alone).
        """
        run = self._runs.get(conversation_id)
        if run is None or run.task.done():
            return False
        self._mark_user_stopped(run)
        with contextlib.suppress(Exception):
            from agentcore.runtime.coordination.session import (
                cancel_coordination_on_user_stop,
            )

            cancel_coordination_on_user_stop(conversation_id)
        run.task.cancel()
        logger.info("turn_run.stop", conversation_id=conversation_id, run_id=run.run_id)
        return True

    def is_user_stop(self, conversation_id: str) -> bool:
        """True when the current (or still-unwinding superseded) run is a hard 停止.

        Checks the calling task first so an overlap-cancelled older task still
        salvages as user-stop after the newer run has taken the registry slot.
        """
        task = asyncio.current_task()
        if task is not None and getattr(task, _TASK_USER_STOPPED, False):
            return True
        run = self._runs.get(conversation_id)
        return bool(run is not None and run.user_stopped)

    def is_clean_cancel(self, conversation_id: str) -> bool:
        """True when CancelledError should terminal-close + release (not orphan).

        Covers explicit ``/stop`` (and overlap supersede) plus lifespan shutdown
        salvage. True hard kill without lifespan still orphans.
        """
        return self.is_user_stop(conversation_id) or self.is_shutdown_salvage()

    def live_runs(self) -> list[TurnRun]:
        """Snapshot of runs whose tasks are still not done."""
        return [run for run in self._runs.values() if not run.task.done()]

    async def drain(self, conversation_id: str, *, timeout: float = 10.0) -> bool:
        """Wait for any live run to finish WITHOUT cancelling it (resume preflight).

        D9: a cold paused session may already be running a *new* turn. Resume must not
        ``cancel`` that work — only wait briefly for residual unwind of an already-finalized
        turn (挂起即收口). Returns ``True`` when the slot is clear (idle, or unwind finished
        within ``timeout``); ``False`` when a live task remains — the resume route should
        409 ``turn_in_progress`` and leave the frame unclaimed.
        """
        run = self._runs.get(conversation_id)
        if run is None or run.task.done():
            return True
        logger.info(
            "turn_run.drain",
            conversation_id=conversation_id,
            run_id=run.run_id,
            timeout=timeout,
        )
        await asyncio.wait({run.task}, timeout=timeout)
        run = self._runs.get(conversation_id)
        return run is None or run.task.done()

    async def stop_and_drain(self, conversation_id: str, *, timeout: float = 10.0) -> bool:
        """Cancel the conversation's live run AND await its unwind (explicit ``/stop``).

        Fire-and-forget :meth:`stop` signals cancel; this waits for unwind so the caller
        can take the folder ``workspace_lock`` next. Resume uses :meth:`drain` instead —
        it must not cancel a D9 in-flight new turn. Returns ``True`` if a live run was
        found and signalled.
        """
        run = self._runs.get(conversation_id)
        if run is None or run.task.done():
            return False
        task = run.task
        # Same flag as :meth:`stop` — must mark before cancel.
        if not self.stop(conversation_id):
            return False
        # ``asyncio.wait`` never re-raises the task's (CancelledError) result; a timeout just
        # means it is still unwinding.
        await asyncio.wait({task}, timeout=timeout)
        return True

    async def stop_all_and_drain(self, *, timeout: float = 20.0) -> list[TurnRun]:
        """Cancel every live turn like ``/stop`` and await unwind up to ``timeout``.

        Returns runs still live after the wait — caller must force-close + release
        their leases (graceful shutdown must not fall through to orphan).
        """
        live = self.live_runs()
        if not live:
            return []
        tasks: list[asyncio.Task] = []
        for run in live:
            self._mark_user_stopped(run)
            with contextlib.suppress(Exception):
                from agentcore.runtime.coordination.session import (
                    cancel_coordination_on_user_stop,
                )

                cancel_coordination_on_user_stop(run.conversation_id)
            if not run.task.done():
                run.task.cancel()
                tasks.append(run.task)
            logger.info(
                "turn_run.shutdown_salvage",
                conversation_id=run.conversation_id,
                run_id=run.run_id,
                message_id=run.sink.message_id,
            )
        if tasks:
            await asyncio.wait(set(tasks), timeout=timeout)
        return [run for run in live if not run.task.done()]


# Module-level singleton (single-worker posture, as approvals / interaction).
turn_runs = TurnRunRegistry()


async def salvage_turns_on_shutdown(*, timeout: float | None = None) -> None:
    """Lifespan shutdown: interrupt live turns, await unwind, force-close leftovers.

    Sets the process-wide shutdown flag first so any racing ``CancelledError``
    (uvicorn teardown) takes the clean-close path instead of orphaning. Timed-out
    runs are force-closed; lease is released only when close succeeds, otherwise
    orphaned so the sweeper can retry (never leave a lease-less RUNNING).
    """
    from agentcore.config import settings

    grace = float(timeout) if timeout is not None else float(settings.turn_shutdown_grace_seconds)
    turn_runs.begin_shutdown_salvage()
    leftovers = await turn_runs.stop_all_and_drain(timeout=grace)
    if not leftovers:
        return
    from agentcore.conversation.turn_persistence import close_user_stop_turn
    from agentcore.runtime.leases import orphan_turn_lease, release_turn_lease
    from agentcore.runtime.turn_interrupt import (
        TurnInterruptReason,
        close_turn_interrupted,
    )

    for run in leftovers:
        message_id = run.sink.message_id
        if not message_id:
            logger.warning(
                "turn_run.shutdown_force_release",
                conversation_id=run.conversation_id,
                run_id=run.run_id,
                released=False,
                reason="missing_message_id",
            )
            continue
        closed = False
        with contextlib.suppress(Exception):
            closed = await close_user_stop_turn(
                sink=run.sink,
                conversation_id=run.conversation_id,
                trace_id="",
                message_id=message_id,
            )
        if not closed:
            with contextlib.suppress(Exception):
                closed = await close_turn_interrupted(
                    message_id=message_id,
                    conversation_id=run.conversation_id,
                    reason=TurnInterruptReason.USER_STOP,
                    load_stream_state=True,
                )
        if closed:
            await release_turn_lease(message_id)
        else:
            with contextlib.suppress(Exception):
                await orphan_turn_lease(message_id)
        logger.info(
            "turn_run.shutdown_force_release",
            conversation_id=run.conversation_id,
            run_id=run.run_id,
            message_id=message_id,
            closed=closed,
            released=bool(closed),
        )
