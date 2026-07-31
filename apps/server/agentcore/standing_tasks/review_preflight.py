"""Preflight for daily conversation review — empty-scope hard gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agentcore.db.base import async_session_factory
from agentcore.db.repositories import ConversationRepository
from agentcore.standing_tasks.templates import normalize_template_config


async def count_recent_conversations_in_scope(
    *,
    user_id: str,
    template_config: dict[str, Any] | None,
    exclude_conversation_id: str | None = None,
) -> int:
    """Count chat-mode conversations matching the review scope (lookback window)."""
    cfg = normalize_template_config(template_config)
    lookback = int(cfg["lookback_hours"])
    updated_after = datetime.now(UTC) - timedelta(hours=lookback)
    include_global = bool(cfg["include_global"])
    folder_ids: list[str] = list(cfg["folder_ids"])

    total = 0
    async with async_session_factory() as session:
        repo = ConversationRepository(session)
        if include_global:
            rows = await repo.search(
                user_id,
                "",
                limit=30,
                updated_after=updated_after,
                global_chats_only=True,
                exclude_conversation_id=exclude_conversation_id,
            )
            total += len(rows)
        for fid in folder_ids:
            rows = await repo.search(
                user_id,
                "",
                limit=30,
                updated_after=updated_after,
                folder_id=fid,
                exclude_conversation_id=exclude_conversation_id,
            )
            total += len(rows)
    return total


EMPTY_REVIEW_SUMMARY = "今日无新料：作用域内没有近期可复盘的对话。"
