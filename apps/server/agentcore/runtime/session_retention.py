"""Idle TTL sweep for persisted 留人 sessions — 默认禁用的存储保护兜底.

现场保留语义「对话在，现场就在」（同人连续委派拍板）：现场随删对话级联清理
（ConversationRepository → run_sessions），不按时长过期。本 sweep 仅当显式配置
``session_roster_retention_days > 0`` 时启用（放量后的存储保护兜底）；启用时
``updated_at`` 随每次续写前移，活跃现场不会被清。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.repositories import RunSessionRepository

logger = get_logger(__name__)


async def run_session_retention_sweep() -> int:
    """Delete every session idle past the retention window; return rows removed.

    Batched (``session_roster_sweep_batch_limit`` per round) so a large backlog is
    cleared without one huge transaction. The cutoff is tz-aware UTC, matching how
    ``run_sessions.updated_at`` is stamped (server ``now()``)."""
    if not settings.session_roster_persist_enabled:
        return 0
    # 「对话在，现场就在」：retention_days <= 0 = 按时长清扫禁用（默认）。现场随删对话
    # 级联清理；本 sweep 仅在放量后显式配置 >0 时作为存储保护兜底。
    if settings.session_roster_retention_days <= 0:
        return 0
    before = datetime.now(UTC) - timedelta(days=settings.session_roster_retention_days)
    limit = settings.session_roster_sweep_batch_limit
    total = 0
    async with async_session_factory() as session:
        repo = RunSessionRepository(session)
        while True:
            deleted = await repo.delete_stale(before=before, limit=limit)
            total += deleted
            if deleted < limit:
                break
    if total:
        logger.info("session.retention_swept", deleted=total)
    return total


async def session_retention_loop() -> None:
    """Run :func:`run_session_retention_sweep` forever on the configured interval.
    Cancelled cleanly on shutdown."""
    interval = settings.session_roster_sweep_interval_seconds
    while True:
        try:
            await run_session_retention_sweep()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a failed sweep must not kill the loop
            # Best-effort backstop, logged on ONE line (no traceback) so a recurring
            # transient can't flood the AI logs. A schema fault (e.g. run_sessions
            # missing = pending migration) is persistent, not transient — escalate it
            # to error so a watchdog catches the whole sweep silently failing forever.
            log = logger.error if is_schema_error(e) else logger.warning
            log("session.retention_failed", error=str(e))
        await asyncio.sleep(interval)
