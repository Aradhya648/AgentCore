"""TTL sweep for append-only agent audit events (Phase 2 retention)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.repositories import AgentAuditEventRepository

logger = get_logger(__name__)


async def run_audit_retention_sweep() -> int:
    """Delete audit rows older than ``audit_retention_days``; return rows removed.

    The cutoff is tz-aware UTC, matching how ``agent_audit_events.created_at`` is
    stamped (``DateTime(timezone=True)`` / server ``now()``); a naive local ``now()``
    would shift the TTL boundary by the host offset on non-UTC deployments."""
    before = datetime.now(UTC) - timedelta(days=settings.audit_retention_days)
    limit = settings.audit_retention_sweep_batch_limit
    total = 0
    async with async_session_factory() as session:
        repo = AgentAuditEventRepository(session)
        while True:
            deleted = await repo.delete_stale(before=before, limit=limit)
            total += deleted
            if deleted < limit:
                break
    if total:
        logger.info("audit.retention_swept", deleted=total)
    return total


async def audit_retention_loop() -> None:
    """Run :func:`run_audit_retention_sweep` forever on the configured interval."""
    interval = settings.audit_retention_sweep_interval_seconds
    while True:
        try:
            await run_audit_retention_sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a failed sweep must not kill the loop
            log = logger.error if is_schema_error(e) else logger.warning
            log("audit.retention_failed", error=str(e))
        await asyncio.sleep(interval)
