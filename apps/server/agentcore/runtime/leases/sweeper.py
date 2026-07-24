"""Startup + periodic sweeper for expired RUNNING turn leases.

When a process dies mid-turn, its lease heartbeat stops. This loop claims expired
leases and routes each through :func:`agentcore.runtime.recover.recover_turn` so
unfinished DAG nodes redrive from the journal projection (completed nodes skipped).

Paused turns are owned by ``paused_turns`` (not leases) — a lease that coexists with
a paused frame is released without redrive. Terminal journals (``turn_end``) likewise
drop the stale lease.

No-DAG mid-flight turns (pure chat crash) are salvaged via
:func:`agentcore.runtime.turn_interrupt.close_turn_interrupted` instead of being skipped.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.repositories import PausedTurnRepository, TurnJournalRepository
from agentcore.runtime.journal.entries import KIND_TURN_END
from agentcore.runtime.leases.repo import TurnLeaseRepository
from agentcore.runtime.leases.service import lease_owner_id, orphan_turn_lease, release_turn_lease
from agentcore.runtime.turn_interrupt import TurnInterruptReason, close_turn_interrupted
from agentcore.runtime.turn_state import TurnState

logger = get_logger(__name__)


def _journal_has_turn_end(entries: list[dict]) -> bool:
    return any((e.get("kind") or "") == KIND_TURN_END for e in entries)


async def salvage_interrupted_turn(
    *,
    message_id: str,
    conversation_id: str,
    trace_id: str | None = None,
    reason: str = "process_kill",
) -> bool:
    """Mark a crashed turn incomplete + append ``turn_end`` interrupted.

    Works for pure-chat and unfinished-DAG turns: message status is updated from
    stream_state, and ``turn_end`` is appended at the next journal seq (never
    rewritten from seq=0, which would no-op against an existing DAG prefix).

    Returns ``True`` when the close write succeeded (or was already terminal).
    """
    ok = await close_turn_interrupted(
        message_id=message_id,
        conversation_id=conversation_id,
        trace_id=trace_id,
        reason=reason,
        load_stream_state=True,
    )
    if ok:
        logger.info(
            "turn_lease.sweep_salvage_interrupted",
            message_id=message_id,
            conversation_id=conversation_id,
            reason=reason,
        )
    return ok


async def salvage_no_dag_turn(
    *,
    message_id: str,
    conversation_id: str,
    trace_id: str | None = None,
) -> bool:
    """Close a crashed no-DAG turn (incomplete + turn_end interrupted)."""
    return await salvage_interrupted_turn(
        message_id=message_id,
        conversation_id=conversation_id,
        trace_id=trace_id,
        reason=TurnInterruptReason.PROCESS_KILL.value,
    )


async def run_turn_lease_sweep() -> int:
    """Claim expired leases and kick recover; return number of recoveries started."""
    if not settings.turn_lease_enabled:
        return 0
    before = datetime.now(UTC) - timedelta(seconds=settings.turn_lease_ttl_seconds)
    limit = settings.turn_lease_sweep_batch_limit
    owner = lease_owner_id()
    started = 0

    async with async_session_factory() as session:
        repo = TurnLeaseRepository(session)
        expired = list(await repo.list_expired(before=before, limit=limit))

    for row in expired:
        async with async_session_factory() as session:
            claimed = await TurnLeaseRepository(session).claim_expired(
                row.message_id,
                new_owner_id=owner,
                before=before,
                phase="recovering",
            )
        if claimed is None:
            continue

        # Paused frame owns continuation — drop stale RUNNING lease.
        async with async_session_factory() as session:
            paused = await PausedTurnRepository(session).get(claimed.message_id)
            if paused is not None:
                await TurnLeaseRepository(session).release(claimed.message_id)
                logger.info(
                    "turn_lease.sweep_skip_paused",
                    message_id=claimed.message_id,
                )
                continue

            entries = await TurnJournalRepository(session).load_owned(
                claimed.message_id, claimed.conversation_id
            )

        if entries and _journal_has_turn_end(entries):
            async with async_session_factory() as session:
                await TurnLeaseRepository(session).release(claimed.message_id)
            logger.info(
                "turn_lease.sweep_skip_terminal",
                message_id=claimed.message_id,
                entries=len(entries),
            )
            continue

        state = TurnState.from_journal(entries or [])
        if state.plan is not None and state.unfinished_run_ids:
            logger.info(
                "turn_lease.sweep_recover",
                message_id=claimed.message_id,
                conversation_id=claimed.conversation_id,
                unfinished=len(state.unfinished_run_ids),
                completed=len(state.completed),
            )
            # Detached recover — sweeper must not block the loop on a long redrive.
            from agentcore.runtime.recover import recover_expired_lease

            asyncio.create_task(
                recover_expired_lease(claimed, state),
                name=f"recover-lease-{claimed.message_id}",
            )
            started += 1
            continue

        # No unfinished DAG (or empty journal pure-chat) — salvage from stream_state.
        # Success → release lease. Failure → re-orphan so the next sweep can retry
        # (never delete the row after a failed salvage — that leaves a fake pause).
        ok = False
        try:
            ok = await salvage_no_dag_turn(
                message_id=claimed.message_id,
                conversation_id=claimed.conversation_id,
            )
        except Exception as e:  # noqa: BLE001 — never stall the sweeper
            logger.warning(
                "turn_lease.sweep_salvage_failed",
                message_id=claimed.message_id,
                error=str(e),
            )
            ok = False
        if ok:
            await release_turn_lease(claimed.message_id)
        else:
            logger.warning(
                "turn_lease.sweep_salvage_failed",
                message_id=claimed.message_id,
                error="salvage_returned_false",
            )
            with contextlib.suppress(Exception):
                await orphan_turn_lease(claimed.message_id)

    if started:
        logger.info("turn_lease.sweep_started", recoveries=started)
    return started


async def turn_lease_sweep_loop() -> None:
    """Run :func:`run_turn_lease_sweep` forever on the configured interval."""
    # Boot pass first so a restart immediately reclaims orphaned RUNNING turns.
    try:
        await run_turn_lease_sweep()
    except Exception as e:  # noqa: BLE001
        log = logger.error if is_schema_error(e) else logger.warning
        log("turn_lease.boot_sweep_failed", error=str(e))

    interval = settings.turn_lease_sweep_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            await run_turn_lease_sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log = logger.error if is_schema_error(e) else logger.warning
            log("turn_lease.sweep_failed", error=str(e))
