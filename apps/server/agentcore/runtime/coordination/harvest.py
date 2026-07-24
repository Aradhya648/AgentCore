"""Execution harvester: detached drive → journal terminal → system closing turn (pillar C).

When a background drive reaches a terminal state with no attached chat turn, the
harvester:
1. Emits ``execution_completed`` into the host turn journal (DURABLE).
2. Spawns a system-initiated closing turn that adopts the live coordination session
   so CEO consumes the queued ``ALL_COMPLETED`` and synthesizes a final deliverable.
3. Notifies the user (best-effort push).

If a concurrent user turn has already re-attached (``turn_attached=True``), the
harvester no-ops — that turn's CEO will consume ``ALL_COMPLETED``.
"""

from __future__ import annotations

import contextlib

from agentcore.core.logging import get_logger
from agentcore.runtime.coordination.session import (
    CoordinationSession,
    _close_detached_session,
)

logger = get_logger(__name__)


async def harvest_detached_execution(session: CoordinationSession) -> None:
    """Complete journal terminal facts and launch the system closing turn."""
    if session.turn_attached:
        logger.info(
            "coordination.harvest_skipped_reattached",
            execution_id=session.execution_id,
        )
        return
    if session.user_stopped:
        _close_detached_session(session)
        return

    # ``execution_completed`` already emitted in ``finish_detached_coordination``
    # (while the arming turn sink may still be open). Flush host journal so fold
    # sees terminal facts before the closing turn.
    writer = session.host_journal_writer
    if writer is not None:
        with contextlib.suppress(Exception):
            await writer.flush()

    conversation_id = (session.conversation_id or "").strip()
    if not conversation_id:
        logger.warning(
            "coordination.harvest_missing_conversation",
            execution_id=session.execution_id,
        )
        _close_detached_session(session)
        return

    from agentcore.conversation.execution_harvest import run_harvest_closing_turn

    try:
        await run_harvest_closing_turn(
            conversation_id=conversation_id,
            execution_id=session.execution_id,
        )
    except Exception:  # noqa: BLE001 — always clear the registry on failure
        logger.exception(
            "coordination.harvest_closing_turn_failed",
            execution_id=session.execution_id,
            conversation_id=conversation_id,
        )
        _close_detached_session(session)
        return

    # Closing turn's finally releases coordination; if still registered (CEO never
    # adopted), clear here so the registry does not leak.
    from agentcore.runtime.coordination.session import _sessions

    if _sessions.get(session.execution_id) is session and not session.turn_attached:
        _close_detached_session(session)


def emit_execution_completed(session: CoordinationSession) -> None:
    """Push ``execution_completed`` (live sink if open, else host journal).

    Called from :func:`finish_detached_coordination` *before* the async harvest
    task so ``await_live_detached_drive`` owners can still deliver the frame
    before closing the turn sink / sealing outbox READY.
    """
    from agentcore.runtime.events import execution_completed

    event = execution_completed(
        execution_id=session.execution_id,
        conversation_id=session.conversation_id or "",
        completed=len(session.completed_run_ids),
        total=session.total_workers,
        host_turn_id=session.host_turn_id or None,
    )
    sink = session.event_sink
    if sink is not None:
        with contextlib.suppress(Exception):
            sink.emit(event)
            logger.info(
                "coordination.execution_completed_emitted",
                execution_id=session.execution_id,
                completed=len(session.completed_run_ids),
                total=session.total_workers,
            )
            return
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
        "coordination.execution_completed_emitted",
        execution_id=session.execution_id,
        completed=len(session.completed_run_ids),
        total=session.total_workers,
    )


# Back-compat alias (tests / older call sites).
_emit_execution_completed = emit_execution_completed
