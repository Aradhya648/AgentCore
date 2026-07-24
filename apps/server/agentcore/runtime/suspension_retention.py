"""7-day idle TTL sweep for persisted paused turns (结构化挂起 2b turn 级落盘).

Mirrors the recoverable-worker roster retention (``session_retention.py``): a
periodic backstop that deletes ``paused_turns`` rows untouched within the window,
so abandoned plan_review pauses do not grow without bound. The live in-process
path already drops a frame on a connected resolve / timeout; this sweep only
catches the *disconnected, never-resumed* remainder — a turn that paused, lost its
client, and was never continued. A row's ``updated_at`` advances on re-pause
(resume → pause again), so an actively re-paused turn stays alive; one left alone
for the retention window is pruned.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.repositories import PausedTurnRepository

logger = get_logger(__name__)


async def run_paused_turn_retention_sweep() -> int:
    """Delete every paused turn idle past the retention window; return rows removed.

    Batched (``paused_turn_sweep_batch_limit`` per round) so a large backlog is
    cleared without one huge transaction. The cutoff is tz-aware UTC, matching how
    ``paused_turns.updated_at`` is stamped (``datetime.now(UTC)`` / server ``now()``)."""
    if not settings.structured_suspension_persist_enabled:
        return 0
    before = datetime.now(UTC) - timedelta(days=settings.paused_turn_retention_days)
    limit = settings.paused_turn_sweep_batch_limit
    total = 0
    async with async_session_factory() as session:
        repo = PausedTurnRepository(session)
        while True:
            deleted = await repo.delete_stale(before=before, limit=limit)
            total += deleted
            if deleted < limit:
                break
    if total:
        logger.info("suspension.retention_swept", deleted=total)
    return total


async def paused_turn_retention_loop() -> None:
    """Run :func:`run_paused_turn_retention_sweep` forever on the configured interval.
    Cancelled cleanly on shutdown."""
    interval = settings.paused_turn_sweep_interval_seconds
    while True:
        try:
            await run_paused_turn_retention_sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a failed sweep must not kill the loop
            # Best-effort backstop, logged on ONE line (no traceback) so a recurring
            # transient can't flood the AI logs. A schema fault (e.g. paused_turns
            # missing = pending migration) is persistent, not transient — escalate it
            # to error so a watchdog catches the whole sweep silently failing forever.
            log = logger.error if is_schema_error(e) else logger.warning
            log("suspension.retention_failed", error=str(e))
        await asyncio.sleep(interval)
