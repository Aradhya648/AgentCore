"""TTL sweep for terminal refresh_tokens rows (rotated / revoked / expired).

Mirrors paused-turn / audit retention: a periodic backstop that hard-deletes
rows past ``refresh_token_retention_days`` so the table stays bounded while
recent rotated rows remain available for reuse detection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.repositories import RefreshTokenRepository

logger = get_logger(__name__)


async def run_refresh_token_retention_sweep() -> int:
    """Delete terminal refresh rows older than the retention window; return count."""
    if settings.refresh_token_retention_days <= 0:
        return 0
    before = datetime.now(UTC) - timedelta(days=settings.refresh_token_retention_days)
    limit = settings.refresh_token_sweep_batch_limit
    total = 0
    async with async_session_factory() as session:
        repo = RefreshTokenRepository(session)
        while True:
            deleted = await repo.delete_terminal_stale(before=before, limit=limit)
            total += deleted
            if deleted < limit:
                break
    if total:
        logger.info("auth.refresh_retention_swept", deleted=total)
    return total


async def refresh_token_retention_loop() -> None:
    """Run :func:`run_refresh_token_retention_sweep` forever on the configured interval."""
    interval = settings.refresh_token_sweep_interval_seconds
    while True:
        try:
            await run_refresh_token_retention_sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a failed sweep must not kill the loop
            log = logger.error if is_schema_error(e) else logger.warning
            log("auth.refresh_retention_failed", error=str(e))
        await asyncio.sleep(interval)
