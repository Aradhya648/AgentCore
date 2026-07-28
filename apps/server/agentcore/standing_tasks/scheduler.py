"""In-process standing-task scheduler (lifespan DB poll + lease)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.repositories.standing_tasks import StandingTaskRepository
from agentcore.standing_tasks.runner import dispatch_standing_task
from agentcore.standing_tasks.schedule import next_run_after

logger = get_logger(__name__)


async def poll_due_standing_tasks(*, owner: str | None = None) -> int:
    """Claim due tasks and spawn runs. Returns the number of claimed tasks."""
    owner_id = owner or f"sched-{uuid4().hex[:12]}"
    now = datetime.now(UTC)
    lease_seconds = settings.standing_task_lease_seconds
    limit = settings.standing_task_poll_batch_limit

    async with async_session_factory() as session:
        claimed = await StandingTaskRepository(session).claim_due(
            now=now,
            owner=owner_id,
            lease_seconds=lease_seconds,
            limit=limit,
        )

    spawned = 0
    for task in claimed:
        try:
            # Advance next_run_at immediately so a slow job cannot be re-claimed
            # on the next poll; the job still clears the lease when done.
            try:
                # Webhook rows are excluded by claim_due; defense if cron missing.
                if not task.cron:
                    raise ValueError("schedule task missing cron")
                nxt = next_run_after(task.cron, now)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "standing_task.schedule_advance_failed",
                    task_id=task.id,
                    error=str(e),
                )
                nxt = None
            if nxt is not None:
                async with async_session_factory() as session:
                    await StandingTaskRepository(session).advance_next_run(
                        task.id, next_run_at=nxt
                    )
            await dispatch_standing_task(
                task_id=task.id,
                user_id=task.user_id,
                # Already advanced above when possible; otherwise let the job retry.
                advance_schedule=nxt is None,
                lease_owner=owner_id,
                trigger_source="schedule",
            )
            spawned += 1
        except Exception as e:  # noqa: BLE001 — one bad task must not stall the poll
            logger.error(
                "standing_task.dispatch_failed",
                task_id=task.id,
                error=str(e),
                exc_info=True,
            )
            async with async_session_factory() as session:
                await StandingTaskRepository(session).clear_lease(
                    task.id, owner=owner_id
                )
    return spawned


async def standing_task_scheduler_loop() -> None:
    """Poll ``next_run_at`` forever on the configured interval (lifespan task)."""
    interval = settings.standing_task_poll_interval_seconds
    while True:
        try:
            n = await poll_due_standing_tasks()
            if n:
                logger.info("standing_task.poll_spawned", count=n)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log = logger.error if is_schema_error(e) else logger.warning
            log("standing_task.poll_failed", error=str(e))
        await asyncio.sleep(interval)
