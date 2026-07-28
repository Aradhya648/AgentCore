"""Standing-task inbox settlement after a standing conversation turn ends.

Truth source: when a ``mode=standing`` conversation finishes a resume (or re-pauses),
open ``awaiting_user`` run rows follow that outcome. Ack remains a manual dismiss
path for badge; no cross-layer polling.
"""

from __future__ import annotations

from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import PausedTurnRepository
from agentcore.db.repositories.standing_tasks import StandingTaskRunRepository
from agentcore.runtime.events import FinishReason

logger = get_logger(__name__)

_SUMMARY_MAX = 500


def _truncate_summary(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip()
    if len(cleaned) <= _SUMMARY_MAX:
        return cleaned
    return cleaned[: _SUMMARY_MAX - 1] + "…"


def _finish_is_paused(finish: object) -> bool:
    if finish is FinishReason.PAUSED:
        return True
    return getattr(finish, "value", finish) == "paused"


async def settle_after_turn(
    *,
    conversation_id: str,
    finish_reason: object = None,
    content: str | None = None,
    error: str | None = None,
) -> int:
    """Settle open ``awaiting_user`` inbox rows for a standing conversation.

    Returns the number of rows updated. No-op when none are open.
    """
    summary = _truncate_summary(content)
    async with async_session_factory() as session:
        runs = StandingTaskRunRepository(session)
        open_rows = await runs.list_awaiting_for_conversation(conversation_id)
        if not open_rows:
            return 0

        paused = _finish_is_paused(finish_reason)
        if not paused:
            paused = await PausedTurnRepository(session).exists_for_conversation(
                conversation_id
            )

        finish_value = getattr(finish_reason, "value", finish_reason)
        failed = bool(error) or finish_value in ("error", "cancelled")

        updated = 0
        for row in open_rows:
            if paused:
                await runs.mark_awaiting_user(row.id, summary=summary or row.summary)
            elif failed:
                await runs.mark_failed(
                    row.id, error=str(error or "拍板后续回合失败")
                )
            else:
                await runs.mark_succeeded(row.id, summary=summary)
            updated += 1

    logger.info(
        "standing_task.inbox_settled",
        conversation_id=conversation_id,
        count=updated,
        paused=paused,
        failed=failed and not paused,
    )
    return updated
