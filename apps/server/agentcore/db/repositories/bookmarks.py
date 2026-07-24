"""Message bookmark (消息收藏) data access.

A bookmark is a per-user, message-level saved pointer (对话内消息 bookmark → 侧栏
「已收藏」). Server-stored so it is reachable from any device (跨设备). Owner-scoping
is a structural default — every read/mutation is filtered by ``user_id`` — and the
list read INNER JOINs live messages + non-deleted conversations so a dangling
pointer never surfaces.
"""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models import Conversation, Message, MessageBookmark


class BookmarkRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(
        self, *, user_id: str, conversation_id: str, message_id: str
    ) -> MessageBookmark:
        """Idempotently bookmark a message for a user; returns the (new or existing) row.

        The caller has already proven the user owns the message's conversation
        (IDOR-safe). The ``(user_id, message_id)`` unique constraint + ON CONFLICT
        DO NOTHING make a double-tap a harmless no-op rather than a 500 / duplicate;
        the follow-up select returns whichever row now exists so the route can echo
        the created bookmark back to the client.
        """
        await self._session.execute(
            pg_insert(MessageBookmark)
            .values(
                id=new_id(),
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "message_id"])
        )
        await self._session.commit()
        result = await self._session.execute(
            select(MessageBookmark).where(
                MessageBookmark.user_id == user_id,
                MessageBookmark.message_id == message_id,
            )
        )
        return result.scalar_one()

    async def remove(self, *, user_id: str, message_id: str) -> bool:
        """Remove a user's bookmark for a message. Returns whether a row matched.

        Scoped by ``user_id`` so a user can only ever drop their own bookmark;
        removing an absent one is a harmless no-op (False) so un-bookmark is
        idempotent.
        """
        result = await self._session.execute(
            delete(MessageBookmark).where(
                MessageBookmark.user_id == user_id,
                MessageBookmark.message_id == message_id,
            )
        )
        await self._session.commit()
        return (result.rowcount or 0) > 0

    async def list_by_user(
        self, user_id: str, *, limit: int
    ) -> Sequence[tuple[MessageBookmark, Message, str]]:
        """A user's bookmarks (newest-first), each joined to its message + conv title.

        INNER JOINs live messages and non-deleted, non-handoff conversations, so a
        bookmark whose message/conversation was removed (or whose conversation was
        soft-deleted) simply doesn't appear — the「已收藏」view never shows a dead
        pointer. Owner-scoping is doubly enforced (bookmark AND conversation
        ``user_id``). Returns ``(bookmark, message, conversation_title)`` triples.
        """
        result = await self._session.execute(
            select(MessageBookmark, Message, Conversation.title)
            .join(Message, Message.id == MessageBookmark.message_id)
            .join(Conversation, Conversation.id == MessageBookmark.conversation_id)
            .where(
                MessageBookmark.user_id == user_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
                Conversation.mode != "handoff",
            )
            .order_by(MessageBookmark.created_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def list_message_ids_for_conversation(
        self, user_id: str, conversation_id: str
    ) -> list[str]:
        """Ids of a user's bookmarked messages in one conversation (client star state)."""
        result = await self._session.execute(
            select(MessageBookmark.message_id).where(
                MessageBookmark.user_id == user_id,
                MessageBookmark.conversation_id == conversation_id,
            )
        )
        return list(result.scalars().all())
