"""IM chat domain data access (消息页 = 找人): chats, members, messages."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models import Chat, ChatMember, ChatMessage

# Fixed id shared with the official-chat migration so create_all test DBs and
# production converge on the same singleton row.
OFFICIAL_CHAT_ID = "0de7a000-0000-4000-a000-000000000002"
OFFICIAL_CHAT_TITLE = "官方号"


class ChatRepository:
    """IM chat domain (消息页 = 找人): chats, members and their messages.

    Separate from the AI conversation/message repos — the 消息 page is human↔human
    plus an official account, sharing the frontend chat core, not these tables.
    All membership-scoped reads let the service 404 a non-member (IDOR-safe).
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    @staticmethod
    def dm_key(user_a: str, user_b: str) -> str:
        """Canonical pair key (sorted) so a dm is one row regardless of who opens it."""
        return ":".join(sorted([user_a, user_b]))

    async def get_dm(self, user_a: str, user_b: str) -> Chat | None:
        result = await self._session.execute(
            select(Chat).where(Chat.dm_key == self.dm_key(user_a, user_b))
        )
        return result.scalar_one_or_none()

    async def create_dm(
        self, *, creator_id: str, peer_id: str, peer_state: str = "pending"
    ) -> Chat:
        """Open a 1:1 chat. The opener joins accepted; the peer starts ``pending``
        (the stranger message-request gate) until they accept/reply.
        """
        chat = Chat(
            id=new_id(),
            type="dm",
            created_by=creator_id,
            dm_key=self.dm_key(creator_id, peer_id),
        )
        self._session.add(chat)
        self._session.add(ChatMember(chat_id=chat.id, user_id=creator_id, state="accepted"))
        self._session.add(ChatMember(chat_id=chat.id, user_id=peer_id, state=peer_state))
        await self._session.commit()
        await self._session.refresh(chat)
        return chat

    async def get_chat(self, chat_id: str) -> Chat | None:
        result = await self._session.execute(select(Chat).where(Chat.id == chat_id))
        return result.scalar_one_or_none()

    async def list_auto_join_chats(self) -> Sequence[Chat]:
        """Chats every new user is auto-joined to (the 内测全员群 mechanism).

        Queried at registration to enroll the new account; a handful of rows in
        practice (the 内测群 + the official broadcast channel).
        """
        result = await self._session.execute(select(Chat).where(Chat.auto_join.is_(True)))
        return result.scalars().all()

    async def get_official_chat(self) -> Chat | None:
        """The site-wide singleton official broadcast chat (``type=official``).

        At most one row (partial unique index ``uq_chats_official_singleton``).
        """
        result = await self._session.execute(
            select(Chat).where(Chat.type == "official").limit(1)
        )
        return result.scalar_one_or_none()

    async def get_or_create_official_chat(self) -> Chat:
        """Return the official broadcast chat, creating the singleton if missing.

        Production is seeded by migration; this covers create_all test DBs and
        any environment that reached head without the data row.
        """
        existing = await self.get_official_chat()
        if existing is not None:
            return existing
        chat = Chat(
            id=OFFICIAL_CHAT_ID,
            type="official",
            title=OFFICIAL_CHAT_TITLE,
            auto_join=True,
            created_by=None,
        )
        self._session.add(chat)
        try:
            await self._session.commit()
        except IntegrityError:
            # Concurrent create / unique violation — re-read the winner.
            await self._session.rollback()
            existing = await self.get_official_chat()
            if existing is not None:
                return existing
            raise
        await self._session.refresh(chat)
        return chat

    async def add_member(
        self,
        chat_id: str,
        user_id: str,
        *,
        role: str = "member",
        state: str = "accepted",
        pinned: bool = False,
    ) -> None:
        """Add a user to a chat, idempotently.

        A re-add (same chat_id+user_id) is a no-op — registration auto-join and
        the backfill can both touch a user without duplicating or resetting their
        per-chat state (the PK conflict is ignored).
        """
        stmt = (
            pg_insert(ChatMember)
            .values(
                chat_id=chat_id,
                user_id=user_id,
                role=role,
                state=state,
                pinned=pinned,
            )
            .on_conflict_do_nothing(index_elements=["chat_id", "user_id"])
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def remove_member(self, chat_id: str, user_id: str) -> None:
        """Remove a user from a chat (leave-group / admin-kick). Idempotent."""
        await self._session.execute(
            delete(ChatMember).where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
        )
        await self._session.commit()

    async def set_membership_flags(
        self,
        chat_id: str,
        user_id: str,
        *,
        muted: bool | None = None,
        pinned: bool | None = None,
    ) -> None:
        """Update a member's per-chat flags (mute / pin); ``None`` leaves a field."""
        values: dict = {}
        if muted is not None:
            values["muted"] = muted
        if pinned is not None:
            values["pinned"] = pinned
        if not values:
            return
        await self._session.execute(
            update(ChatMember)
            .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
            .values(**values)
        )
        await self._session.commit()

    async def set_admin_mute(self, chat_id: str, user_id: str, *, muted_by_admin: bool) -> None:
        """Set/clear a member's admin-imposed 禁言 (Stage 3 审核治理).

        Separate column from the member's own ``muted`` so moderation and
        self-service don't clobber each other; idempotent (a no-op write is fine).
        """
        await self._session.execute(
            update(ChatMember)
            .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
            .values(muted_by_admin=muted_by_admin)
        )
        await self._session.commit()

    async def get_member(self, chat_id: str, user_id: str) -> ChatMember | None:
        result = await self._session.execute(
            select(ChatMember).where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_members(self, chat_id: str) -> Sequence[ChatMember]:
        result = await self._session.execute(
            select(ChatMember).where(ChatMember.chat_id == chat_id)
        )
        return result.scalars().all()

    async def list_memberships(self, user_id: str) -> Sequence[tuple[Chat, ChatMember]]:
        """A user's chats joined with their per-chat state.

        Pinned chats first (the auto-joined 内测群 is pinned on enrollment so it
        surfaces at the top even before it has any messages), then by recent
        activity (``last_message_at`` desc, NULLs last).
        """
        result = await self._session.execute(
            select(Chat, ChatMember)
            .join(ChatMember, ChatMember.chat_id == Chat.id)
            .where(ChatMember.user_id == user_id)
            .order_by(
                ChatMember.pinned.desc(),
                Chat.last_message_at.desc().nullslast(),
            )
        )
        return [(row[0], row[1]) for row in result.all()]

    async def peer_ids_for(
        self, chat_ids: Sequence[str], *, exclude_user_id: str
    ) -> dict[str, str]:
        """Map each chat id → one other member's id (the dm peer). Batch lookup to
        resolve list-row names without an N+1.
        """
        if not chat_ids:
            return {}
        result = await self._session.execute(
            select(ChatMember.chat_id, ChatMember.user_id).where(
                ChatMember.chat_id.in_(chat_ids),
                ChatMember.user_id != exclude_user_id,
            )
        )
        out: dict[str, str] = {}
        for chat_id, uid in result.all():
            out.setdefault(chat_id, uid)
        return out

    async def list_co_member_ids(self, user_id: str) -> list[str]:
        """Distinct user ids that share ≥1 chat with ``user_id`` (excludes self).

        Audience for presence fan-out: anyone who can see this user in a dm peer
        slot or a group roster — not a site-wide broadcast.
        """
        my_chats = select(ChatMember.chat_id).where(ChatMember.user_id == user_id)
        result = await self._session.execute(
            select(ChatMember.user_id)
            .where(
                ChatMember.chat_id.in_(my_chats),
                ChatMember.user_id != user_id,
            )
            .distinct()
        )
        return [row[0] for row in result.all()]

    async def get_message(self, message_id: str) -> ChatMessage | None:
        """Load one message by id (no membership gate — service validates chat)."""
        result = await self._session.execute(
            select(ChatMessage).where(ChatMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def add_message(
        self,
        *,
        chat_id: str,
        sender_user_id: str | None,
        content: str,
        sender_type: str = "user",
        content_type: str = "text",
        attachments: list | None = None,
        payload: dict | None = None,
        reply_to_message_id: str | None = None,
        reply_to: dict | None = None,
        mentions: list | None = None,
        client_msg_id: str | None = None,
    ) -> ChatMessage:
        """Append a message and refresh the chat's list-row preview.

        Idempotent for human sends: a retry with the same ``client_msg_id`` returns
        the already-stored row instead of duplicating (the unique index is the
        backstop). The chat's ``last_message_*`` are bumped so the list re-sorts.
        ``reply_to`` is the frozen quote snapshot (paired with ``reply_to_message_id``).
        ``mentions`` is the frozen @list (empty when omitted).
        """
        if client_msg_id is not None and sender_user_id is not None:
            existing = await self._session.execute(
                select(ChatMessage).where(
                    ChatMessage.chat_id == chat_id,
                    ChatMessage.sender_user_id == sender_user_id,
                    ChatMessage.client_msg_id == client_msg_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row is not None:
                return row
        msg = ChatMessage(
            id=new_id(),
            chat_id=chat_id,
            sender_user_id=sender_user_id,
            sender_type=sender_type,
            content=content,
            content_type=content_type,
            reply_to_message_id=reply_to_message_id,
            reply_to=reply_to,
            mentions=list(mentions) if mentions is not None else [],
            client_msg_id=client_msg_id,
        )
        if attachments is not None:
            msg.attachments = attachments
        if payload is not None:
            msg.payload = payload
        self._session.add(msg)
        await self._session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(
                last_message_at=datetime.now(UTC),
                last_message_preview=(content or "")[:200],
            )
        )
        await self._session.commit()
        await self._session.refresh(msg)
        return msg

    async def recall_message(
        self,
        *,
        message_id: str,
        recalled_by_user_id: str,
        list_preview: str,
    ) -> ChatMessage | None:
        """Soft-recall a message: keep the row, clear body, refresh list preview.

        Idempotent when already recalled. ``list_preview`` is written onto the
        chat only when this message is still the latest (by ``created_at``).
        """
        msg = await self.get_message(message_id)
        if msg is None:
            return None
        if msg.recalled_at is not None:
            return msg
        now = datetime.now(UTC)
        msg.recalled_at = now
        msg.recalled_by_user_id = recalled_by_user_id
        msg.content = None
        msg.attachments = []
        msg.payload = None

        latest = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_id == msg.chat_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        latest_msg = latest.scalar_one_or_none()
        if latest_msg is not None and latest_msg.id == msg.id:
            await self._session.execute(
                update(Chat)
                .where(Chat.id == msg.chat_id)
                .values(last_message_preview=list_preview[:200])
            )

        await self._session.commit()
        await self._session.refresh(msg)
        return msg

    async def edit_message(
        self,
        *,
        message_id: str,
        content: str,
        list_preview: str | None,
    ) -> ChatMessage | None:
        """Rewrite plain-text content and stamp ``edited_at``.

        When ``list_preview`` is provided and this message is still the chat's
        latest (by ``created_at``), refresh ``chats.last_message_preview``.
        """
        msg = await self.get_message(message_id)
        if msg is None:
            return None
        now = datetime.now(UTC)
        msg.content = content
        msg.edited_at = now

        if list_preview is not None:
            latest = await self._session.execute(
                select(ChatMessage)
                .where(ChatMessage.chat_id == msg.chat_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(1)
            )
            latest_msg = latest.scalar_one_or_none()
            if latest_msg is not None and latest_msg.id == msg.id:
                await self._session.execute(
                    update(Chat)
                    .where(Chat.id == msg.chat_id)
                    .values(last_message_preview=list_preview[:200])
                )

        await self._session.commit()
        await self._session.refresh(msg)
        return msg

    async def list_messages(
        self, chat_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[ChatMessage], int]:
        base_query = select(ChatMessage).where(ChatMessage.chat_id == chat_id)
        count_result = await self._session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()
        result = await self._session.execute(
            base_query.order_by(ChatMessage.created_at.asc()).limit(limit).offset(offset)
        )
        return result.scalars().all(), total

    async def mark_read(
        self,
        chat_id: str,
        user_id: str,
        *,
        last_read_message_id: str,
        last_read_at: datetime | None = None,
    ) -> None:
        await self._session.execute(
            update(ChatMember)
            .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
            .values(
                last_read_message_id=last_read_message_id,
                last_read_at=last_read_at or datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def accept_request(self, chat_id: str, user_id: str) -> None:
        """Clear a recipient's pending message-request gate (they accepted/replied)."""
        await self._session.execute(
            update(ChatMember)
            .where(ChatMember.chat_id == chat_id, ChatMember.user_id == user_id)
            .values(state="accepted")
        )
        await self._session.commit()

    async def share_group(self, user_a: str, user_b: str) -> bool:
        """True when both users are members of at least one ``type=group`` chat."""
        b_chats = select(ChatMember.chat_id).where(ChatMember.user_id == user_b)
        result = await self._session.execute(
            select(ChatMember.chat_id)
            .join(Chat, Chat.id == ChatMember.chat_id)
            .where(
                ChatMember.user_id == user_a,
                ChatMember.chat_id.in_(b_chats),
                Chat.type == "group",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def unread_counts(self, user_id: str) -> dict[str, int]:
        """Per-chat unread message counts for a user, keyed by chat id.

        Unread = messages this user did not send, created after their read cursor
        (``last_read_at``; NULL = never read → all count). Official (NULL sender)
        messages count too — ``is_distinct_from`` treats NULL as "not me". One
        GROUP BY for the whole list (no per-chat round-trips).
        """
        result = await self._session.execute(
            select(ChatMessage.chat_id, func.count())
            .select_from(ChatMessage)
            .join(ChatMember, ChatMember.chat_id == ChatMessage.chat_id)
            .where(
                ChatMember.user_id == user_id,
                ChatMessage.sender_user_id.is_distinct_from(user_id),
                or_(
                    ChatMember.last_read_at.is_(None),
                    ChatMessage.created_at > ChatMember.last_read_at,
                ),
            )
            .group_by(ChatMessage.chat_id)
        )
        return {row[0]: row[1] for row in result.all()}
