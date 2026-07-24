"""Cascade-delete helpers for ``turn_journal`` rows.

The ``turn_journal`` replay stream (§8.3 唯一事实源) has no DB foreign key and no
own TTL sweep, so every hard-delete of a conversation or its messages must drop the
matching journal rows in the *same* transaction or they orphan. Centralized here so
all three delete paths — conversation ``hard_delete``, message ``delete_after``,
message ``delete_by_id`` — cascade the journal identically: a future delete path
calls one of these instead of re-inlining ``delete(TurnJournalRow)`` and risking a
missed cascade (the invariant-drift risk that motivated extracting this).

None of these commit; the calling repository commits the surrounding unit of work,
so the cascade stays atomic with the row delete it accompanies.
"""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models import Message, TurnJournalRow


async def delete_journal_for_conversation(session: AsyncSession, conversation_id: str) -> None:
    """Drop every journal row of a conversation (whole-conversation hard delete)."""
    await session.execute(
        delete(TurnJournalRow).where(TurnJournalRow.conversation_id == conversation_id)
    )


async def delete_journal_after(
    session: AsyncSession, conversation_id: str, *, after_created_at: datetime
) -> None:
    """Drop journal rows of a conversation's messages created strictly after a point.

    The message-side of regenerate / edit-and-resend (drops the superseded tail);
    the ``turn_id`` subquery is resolved before the messages themselves are deleted.
    """
    await session.execute(
        delete(TurnJournalRow).where(
            TurnJournalRow.turn_id.in_(
                select(Message.id).where(
                    Message.conversation_id == conversation_id,
                    Message.created_at > after_created_at,
                )
            )
        )
    )


async def delete_journal_for_message(
    session: AsyncSession, conversation_id: str, message_id: str
) -> None:
    """Drop one message's journal rows (单条消息删除), conversation-scoped so a
    cross-tenant id touches nothing."""
    await session.execute(
        delete(TurnJournalRow).where(
            TurnJournalRow.turn_id == message_id,
            TurnJournalRow.conversation_id == conversation_id,
        )
    )
