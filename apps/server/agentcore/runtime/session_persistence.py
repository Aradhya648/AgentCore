"""DB-backed load / save for the 留人 roster (乙 热修 P3 跨进程落盘).

Bridges the DB-unaware roster + tools to the ``run_sessions`` table. The pipeline
wires these closures into ``delegate`` (write-through after a worker finishes) and
``revise`` (load-on-miss + write-through after a revision), so neither tool nor the
pipeline imports the DB layer. Uses ``telemetry_session_factory`` (not an injected
request session / primary pool), matching the cost-ledger / journal / audit
telemetry posture so roster writes never starve content persistence.

Hot-path write-through is fire-and-forget via :class:`SessionRosterWriter`
(audit-aligned ``schedule`` + turn-end ``flush``); same-turn revise hits the
in-memory roster (``register_sessions`` / ``SessionStore.put``), so DB latency
never blocks the turn. Flush at pipeline teardown keeps cross-turn /
cross-process load-on-miss durable.

All operations are best-effort: a persistence failure logs and degrades to P2
in-memory behaviour (a miss → 回落甲) rather than breaking the user's turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from agentcore.core.log_context import get_log_value
from agentcore.core.logging import get_logger
from agentcore.db.base import telemetry_session_factory
from agentcore.db.repositories import RunSessionRepository
from agentcore.runtime.runs.serialize import session_from_row, session_to_row
from agentcore.runtime.runs.session import RunSession

logger = get_logger(__name__)

type _SessionSave = Callable[[RunSession], Awaitable[None]]


async def save_run_session(conversation_id: str, session: RunSession) -> None:
    """Write-through persist one recoverable session (best-effort).

    Stamps the ambient turn ``trace_id`` (this runs inside the pipeline's trace
    scope, so contextvars carry it) so the persisted worker links back to its
    originating interaction's logs. Uses the telemetry pool so roster writes
    never starve content persistence (as-built: 成本配额 §三).
    """
    row = session_to_row(session)
    try:
        async with telemetry_session_factory() as db:
            await RunSessionRepository(db).upsert(
                conversation_id=conversation_id,
                trace_id=get_log_value("trace_id") or None,
                **row,
            )
    except Exception as e:  # noqa: BLE001 — persistence must never break the turn
        logger.warning("session.persist_failed", run_id=session.run_id, error=str(e))


async def load_run_session(run_id: str) -> RunSession | None:
    """Rehydrate a persisted session by ``run_id`` (best-effort); ``None`` on miss
    or error (→ 回落甲 at the call site)."""
    try:
        async with telemetry_session_factory() as db:
            row = await RunSessionRepository(db).get(run_id)
    except Exception as e:  # noqa: BLE001 — a load failure degrades to a roster miss
        logger.warning("session.load_failed", run_id=run_id, error=str(e))
        return None
    return session_from_row(row) if row is not None else None


class SessionRosterWriter:
    """Per-turn fire-and-forget roster write-through (mirrors ``AuditRecorder``).

    Tools keep calling the ``SessionSaver`` awaitable; ``save`` schedules the
    underlying DB write onto the event loop and returns immediately. The pipeline
    ``flush``es pending tasks at the same turn-end points as audit so every
    scheduled write lands before the turn yields (cross-turn revise durability).

    Same ``run_id`` re-schedules coalesce: a later revise supersedes an in-flight
    write so flush cannot leave a stale upsert behind a newer memory state.
    """

    def __init__(self, save: _SessionSave) -> None:
        self._save = save
        self._pending: list[asyncio.Task[None]] = []
        self._by_run_id: dict[str, asyncio.Task[None]] = {}

    @classmethod
    def wrap(cls, save: _SessionSave | None) -> SessionRosterWriter | None:
        """Bind a writer around an injected saver, or ``None`` when persistence is off."""
        return cls(save) if save is not None else None

    async def save(self, session: RunSession) -> None:
        """``SessionSaver``-compatible entry: schedule write-through, do not await DB."""
        self.schedule(session)

    def schedule(self, session: RunSession) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        prev = self._by_run_id.pop(session.run_id, None)
        if prev is not None and not prev.done():
            prev.cancel()
            if prev in self._pending:
                self._pending.remove(prev)
        task = loop.create_task(self._save(session))
        self._pending.append(task)
        self._by_run_id[session.run_id] = task

        def _done(t: asyncio.Task[None], *, run_id: str = session.run_id) -> None:
            if t in self._pending:
                self._pending.remove(t)
            if self._by_run_id.get(run_id) is t:
                del self._by_run_id[run_id]

        task.add_done_callback(_done)

    async def flush(self) -> None:
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)
