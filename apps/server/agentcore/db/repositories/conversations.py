"""Conversation data access (the chat itself; shares/folders/messages are siblings)."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models import (
    Conversation,
    CostEvent,
    MemoryUpdateRow,
    Message,
    MessageBookmark,
    TurnLeaseRow,
    TurnMetricsRow,
    User,
)

from ._audit_cascade import delete_audit_for_conversation
from ._base import _ilike_pattern, _sum_int
from ._journal_cascade import delete_journal_for_conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        title: str | None = None,
        folder_id: str | None = None,
        mode: str = "chat",
        local_container_root_id: str | None = None,
        permission_preset: str | None = None,
        deep_research_auto: bool | None = None,
    ) -> Conversation:
        # Omit title when not provided so the DB server_default ('') applies.
        # The live `conversations.title` column is NOT NULL; passing an explicit
        # None would emit `INSERT ... title=NULL` and violate the constraint.
        #
        # ``folder_id`` files the chat at creation (a "新建对话 from a folder"):
        # filing it here, rather than with a follow-up move, keeps a chat born in a
        # folder in its folder's workspace from its very first turn — and avoids
        # racing the workspace-lock guard, which would otherwise reject the move
        # once that first turn has landed a message (双模式工作区 §九 ⑩).
        #
        # ``mode`` is "chat" for a normal conversation; a "handoff" conversation is
        # the hidden host for a local→云 cloud job's team run (双模式工作区 P2e /
        # e2), kept out of the sidebar by the list filters below.
        conv = Conversation(id=new_id(), user_id=user_id)
        if title is not None:
            conv.title = title
        if folder_id is not None:
            conv.folder_id = folder_id
        if mode != "chat":
            conv.mode = mode
        # Desktop local-container hint for 裸聊: effective bind may fall back to this
        # when ``local_root_id`` is unset (双模式工作区). NULL = cloud intent. Project
        # chats ignore it (inherit the folder's immutable binding). Auto-promote is vetoed.
        if local_container_root_id is not None:
            conv.local_container_root_id = local_container_root_id
        if permission_preset is not None:
            conv.permission_preset = permission_preset
        if deep_research_auto is not None:
            conv.deep_research_auto = bool(deep_research_auto)
        self._session.add(conv)
        await self._session.commit()
        await self._session.refresh(conv)
        return conv

    async def set_permission_preset(
        self, conversation_id: str, *, user_id: str, permission_preset: str
    ) -> Conversation | None:
        """Owner-scoped update of the session permission mode. Returns None if missing."""
        conv = await self.get_by_id(conversation_id, user_id=user_id)
        if not conv:
            return None
        conv.permission_preset = permission_preset
        await self._session.commit()
        await self._session.refresh(conv)
        return conv

    async def set_model_profile(
        self,
        conversation_id: str,
        model_profile_id: str | None,
        *,
        user_id: str,
    ) -> Conversation | None:
        """Owner-scoped set/clear of the session model combination pin.

        ``None`` clears the pin so the conversation follows the account default
        profile. A non-null id is validated by the caller (crud PATCH) before it
        reaches here.
        """
        conv = await self.get_by_id(conversation_id, user_id=user_id)
        if not conv:
            return None
        conv.model_profile_id = model_profile_id
        await self._session.commit()
        await self._session.refresh(conv)
        return conv

    async def clear_model_profile_refs(self, user_id: str, profile_id: str) -> int:
        """Null out conversation pins that reference a deleted profile."""
        from sqlalchemy import update as sa_update

        result = await self._session.execute(
            sa_update(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.model_profile_id == profile_id,
            )
            .values(model_profile_id=None)
        )
        await self._session.commit()
        return int(result.rowcount or 0)

    async def set_deep_research_auto(
        self, conversation_id: str, enabled: bool, *, user_id: str
    ) -> Conversation | None:
        """Owner-scoped toggle of 深度研究自治. Returns None if missing."""
        conv = await self.get_by_id(conversation_id, user_id=user_id)
        if not conv:
            return None
        conv.deep_research_auto = bool(enabled)
        await self._session.commit()
        await self._session.refresh(conv)
        return conv

    async def increment_deep_research_auto_debate_count(
        self, conversation_id: str
    ) -> int:
        """Bump the session auto-debate counter (unscoped; trusted runtime path).

        Returns the new count. Missing conversation ⇒ 0 (no-op).
        """
        conv = await self.get_by_id_unscoped(conversation_id)
        if not conv:
            return 0
        conv.deep_research_auto_debate_count = int(
            conv.deep_research_auto_debate_count or 0
        ) + 1
        await self._session.commit()
        await self._session.refresh(conv)
        return int(conv.deep_research_auto_debate_count)

    async def get_by_id(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        """Owner-scoped fetch: a non-owner (or unknown id) gets None, which the route
        turns into a 404 — no cross-user access nor existence leak.

        ``user_id`` is mandatory so owner-scoping is the structural default rather than
        a caller convention (SEC-002). Trusted internal / admin callers that legitimately
        cross owners use :meth:`get_by_id_unscoped`.
        """
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.deleted_at.is_(None),
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_unscoped(self, conversation_id: str) -> Conversation | None:
        """Cross-owner fetch for trusted internal / admin callers — the turn pipeline,
        background consolidation/compaction, admin cross-user views — that operate on an
        already-authorized ``conversation_id`` without a user in hand.

        The explicit ``_unscoped`` name keeps the un-scoped surface greppable and out of
        user-facing routes (SEC-002); it is not reachable from a user request without an
        upstream owner check.
        """
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_folder_id(self, conversation_id: str) -> str | None:
        """The conversation's ``folder_id`` straight from the DB, bypassing the
        identity map — the idempotent re-check for lazy promotion (工作区对称化 D1a
        §并发提升).

        A scalar *column* read, not a full-entity load, so it returns the live DB
        value even when this session already holds a stale full ``Conversation``
        (under ``expire_on_commit=False`` a committed object is never auto-expired).
        That lets the loser of two racing first-writes see the winner's just-committed
        folder under the promotion lock and reuse it instead of minting a duplicate.
        Returns None when the conversation has no folder yet (or doesn't exist).
        """
        result = await self._session.execute(
            select(Conversation.folder_id).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        archived: bool = False,
    ) -> tuple[Sequence[Conversation], int]:
        # Hidden handoff-job conversations (双模式工作区 P2e / e2) never show in the
        # sidebar — they exist only to host a cloud run's messages/cost/journal.
        # ``archived`` selects one side of the archive split: the default (False) is
        # the live list (sidebar / 全部对话), True backs the「已归档」view.
        base_query = select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
            Conversation.mode != "handoff",
            Conversation.archived == archived,
        )

        count_result = await self._session.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        # Pinned float to the top (置顶对话), then most-recent activity.
        result = await self._session.execute(
            base_query.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total

    async def list_admin(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        query: str | None = None,
        user_id: str | None = None,
        has_errors: bool | None = None,
        include_deleted: bool = True,
        since: datetime | None = None,
        until: datetime | None = None,
        sort: str = "updated_at",
        order: str = "desc",
    ) -> tuple[Sequence[tuple[Conversation, User | None]], int]:
        """Cross-user conversation roster for the admin 对话 page.

        Excludes hidden handoff-host conversations (same as the user sidebar).
        ``include_deleted`` controls soft-deleted conversations; owner identity
        is always joined (tombstone accounts carry ``User.deleted_at``). Filters
        AND-combine: ``query`` ILIKEs title, ``user_id`` scopes to one account,
        ``has_errors`` keeps only conversations with ≥1 errored turn,
        ``since``/``until`` bound ``updated_at`` (inclusive).
        """
        cost_subq = (
            select(
                CostEvent.conversation_id.label("conversation_id"),
                _sum_int(CostEvent.cost_total_nano).label("cost_total"),
            )
            .group_by(CostEvent.conversation_id)
            .subquery()
        )
        base = (
            select(Conversation, User)
            .outerjoin(User, User.user_id == Conversation.user_id)
            .outerjoin(cost_subq, cost_subq.c.conversation_id == Conversation.id)
            .where(Conversation.mode != "handoff")
        )
        if not include_deleted:
            base = base.where(Conversation.deleted_at.is_(None))
        if user_id is not None:
            base = base.where(Conversation.user_id == user_id)
        if query:
            base = base.where(Conversation.title.ilike(_ilike_pattern(query)))
        if since is not None:
            base = base.where(Conversation.updated_at >= since)
        if until is not None:
            base = base.where(Conversation.updated_at <= until)
        if has_errors is True:
            error_ids = (
                select(TurnMetricsRow.conversation_id)
                .where(TurnMetricsRow.status == "error")
                .distinct()
                .scalar_subquery()
            )
            base = base.where(Conversation.id.in_(error_ids))
        elif has_errors is False:
            error_ids = (
                select(TurnMetricsRow.conversation_id)
                .where(TurnMetricsRow.status == "error")
                .distinct()
                .scalar_subquery()
            )
            base = base.where(Conversation.id.not_in(error_ids))

        count_result = await self._session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        if sort == "cost":
            sort_col = func.coalesce(cost_subq.c.cost_total, 0)
        elif sort == "created_at":
            sort_col = Conversation.created_at
        else:
            sort_col = Conversation.updated_at
        order_by = sort_col.asc() if order == "asc" else sort_col.desc()
        offset = (page - 1) * page_size
        result = await self._session.execute(
            base.order_by(order_by).limit(page_size).offset(offset)
        )
        return result.all(), total

    async def search(
        self,
        user_id: str,
        query: str,
        *,
        limit: int,
        updated_after: datetime | None = None,
        folder_id: str | None = None,
    ) -> Sequence[Conversation]:
        """Owner-scoped title substring search (全局搜索 Tier 1).

        ILIKE over ``title``, newest-activity first, capped at ``limit``. Excludes
        soft-deleted and hidden handoff-host conversations — the same visibility as
        the sidebar list, so a hit is always something the user can actually open.

        The optional facets (搜索结果过滤) narrow the same result set server-side so
        the cap is spent on matching rows rather than filtered-away ones:
        ``updated_after`` keeps only recently-active chats (时间过滤), ``folder_id``
        scopes to one folder/工作区.
        """
        stmt = select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
            Conversation.mode != "handoff",
            Conversation.title.ilike(_ilike_pattern(query)),
        )
        if updated_after is not None:
            stmt = stmt.where(Conversation.updated_at >= updated_after)
        if folder_id is not None:
            stmt = stmt.where(Conversation.folder_id == folder_id)
        result = await self._session.execute(
            stmt.order_by(Conversation.updated_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def update_title(
        self, conversation_id: str, title: str, *, user_id: str
    ) -> Conversation | None:
        """Owner-scoped rename (user-facing). ``user_id`` mandatory (SEC-002)."""
        conv = await self.get_by_id(conversation_id, user_id=user_id)
        return await self._write_title(conv, title)

    async def update_title_unscoped(
        self, conversation_id: str, title: str
    ) -> Conversation | None:
        """Title write for trusted internal callers — post-turn auto-title minting — that
        hold an already-authorized ``conversation_id`` but no user (SEC-002)."""
        conv = await self.get_by_id_unscoped(conversation_id)
        return await self._write_title(conv, title)

    async def update_title_if_empty(
        self, conversation_id: str, title: str
    ) -> Conversation | None:
        """Auto-mint write: only when the conversation title is still empty.

        Closes the race with a user rename that lands between schedule and LLM return.
        Returns ``None`` when the row is missing or already titled (no write).
        """
        conv = await self.get_by_id_unscoped(conversation_id)
        if conv is None or (conv.title and str(conv.title).strip()):
            return None
        return await self._write_title(conv, title)

    async def _write_title(
        self,
        conv: Conversation | None,
        title: str,
    ) -> Conversation | None:
        if conv:
            conv.title = title
            await self._session.commit()
            await self._session.refresh(conv)
        return conv

    async def set_pinned(
        self, conversation_id: str, pinned: bool, *, user_id: str
    ) -> Conversation | None:
        """Pin / unpin a conversation (置顶对话). Pinned chats sort to the top of
        the sidebar / list; this only writes the flag."""
        conv = await self.get_by_id(conversation_id, user_id=user_id)
        if conv:
            conv.pinned = pinned
            await self._session.commit()
            await self._session.refresh(conv)
        return conv

    async def set_archived(
        self, conversation_id: str, archived: bool, *, user_id: str
    ) -> Conversation | None:
        """Archive / unarchive a conversation (归档对话, reversible).

        Archiving hides it from the live sidebar / grouped list (it moves to the
        「已归档」view) without deleting it; unarchiving returns it to the list.
        """
        conv = await self.get_by_id(conversation_id, user_id=user_id)
        if conv:
            conv.archived = archived
            await self._session.commit()
            await self._session.refresh(conv)
        return conv

    async def soft_delete(self, conversation_id: str, *, user_id: str) -> bool:
        """Owner-scoped soft delete (user-facing). ``user_id`` mandatory (SEC-002);
        account-wide deletion uses :meth:`soft_delete_all_for_user`."""
        conv = await self.get_by_id(conversation_id, user_id=user_id)
        if conv:
            conv.deleted_at = datetime.now()
            # 现场跟随对话：软删也清 run_sessions，避免唤回已删对话的现场。
            from agentcore.db.repositories.runs import RunSessionRepository

            await RunSessionRepository(self._session).delete_for_conversation(conversation_id)
            await self._session.commit()
            return True
        return False

    async def soft_delete_all_for_user(self, user_id: str) -> int:
        """Soft-delete every live conversation owned by a user (账户注销级联).

        One bulk update so deleting an account doesn't N+1 over its history; already
        soft-deleted rows are skipped. Returns the number newly soft-deleted. The
        retention sweeper later reclaims their workspaces just like any soft delete.
        """
        # Collect ids first so we can cascade-clear run_sessions for those chats.
        ids_result = await self._session.execute(
            select(Conversation.id).where(
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conv_ids = list(ids_result.scalars().all())
        if not conv_ids:
            return 0
        from agentcore.db.models import RunSessionRow

        await self._session.execute(
            delete(RunSessionRow).where(RunSessionRow.conversation_id.in_(conv_ids))
        )
        result = await self._session.execute(
            update(Conversation)
            .where(Conversation.id.in_(conv_ids))
            .values(deleted_at=datetime.now())
        )
        await self._session.commit()
        return int(result.rowcount or 0)

    async def list_purgeable(self, *, before: datetime, limit: int) -> Sequence[Conversation]:
        """Soft-deleted conversations whose ``deleted_at`` is at/older than ``before``.

        Backs retention cleanup (决策⑦): these have outlived the grace period and
        are ready for physical removal. Oldest-deleted first, capped by ``limit``.
        """
        result = await self._session.execute(
            select(Conversation)
            .where(
                Conversation.deleted_at.is_not(None),
                Conversation.deleted_at <= before,
            )
            .order_by(Conversation.deleted_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_ids_by_folder(self, folder_id: str, *, user_id: str) -> list[str]:
        """Every conversation filed in ``folder_id`` (live, archived, or soft-deleted).

        Used by permanent project wipe to cascade hard-delete all member chats.
        Handoff-host conversations are excluded (hidden infra rows).
        """
        result = await self._session.execute(
            select(Conversation.id).where(
                Conversation.user_id == user_id,
                Conversation.folder_id == folder_id,
                Conversation.mode != "handoff",
            )
        )
        return list(result.scalars().all())

    async def hard_delete(self, conversation_id: str) -> None:
        """Physically remove a conversation and all its rows (messages + cost ledger
        + turn journal).

        App-level cascade (no DB FK, per repo convention). Used only by retention
        after the grace period — distinct from ``soft_delete`` (the user-facing
        recoverable delete). The ``turn_journal`` replay stream (唯一事实源, §8.3)
        is dropped here too — it would otherwise orphan (it has no own TTL sweep).
        ``run_sessions`` are also cleared (现场跟随对话).
        """
        await self._session.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        )
        # 消息收藏 pointers into this conversation (app-level cascade; no message left
        # for them to reference after the bulk delete above).
        await self._session.execute(
            delete(MessageBookmark).where(
                MessageBookmark.conversation_id == conversation_id
            )
        )
        await self._session.execute(
            delete(CostEvent).where(CostEvent.conversation_id == conversation_id)
        )
        await delete_journal_for_conversation(self._session, conversation_id)
        await delete_audit_for_conversation(self._session, conversation_id)
        await self._session.execute(
            delete(TurnLeaseRow).where(TurnLeaseRow.conversation_id == conversation_id)
        )
        # Conversation-tail 记忆已更新 records (keyed by conversation_id, no message FK).
        await self._session.execute(
            delete(MemoryUpdateRow).where(MemoryUpdateRow.conversation_id == conversation_id)
        )
        # 现场跟随对话：硬删级联清 run_sessions（与 soft_delete 对称）。
        from agentcore.db.repositories.runs import RunSessionRepository

        await RunSessionRepository(self._session).delete_for_conversation(conversation_id)
        await self._session.execute(delete(Conversation).where(Conversation.id == conversation_id))
        await self._session.commit()

    async def set_memory_synced_at(self, conversation_id: str, synced_at: datetime) -> None:
        """Advance the long-term-memory consolidation watermark (Agent记忆 §1.5).

        ``synced_at`` is the created_at of the last message folded into the user's
        memory. The runner stamps it after each pass (even a no-op one) so neither
        the debounce nor the sweeper reprocesses already-consolidated messages.
        """
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(memory_synced_at=synced_at)
        )
        await self._session.commit()

    async def reset_memory_synced_at_for_user(self, user_id: str) -> int:
        """Clear ``memory_synced_at`` on live chat conversations (memory backfill).

        Only rows that currently hold a watermark are updated, so repeated runs are
        idempotent. Returns the number of conversations reset.
        """
        result = await self._session.execute(
            update(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
                Conversation.mode == "chat",
                Conversation.memory_synced_at.isnot(None),
            )
            .values(memory_synced_at=None)
            .returning(Conversation.id)
        )
        count = len(result.all())
        await self._session.commit()
        return count

    async def count_memory_watermarked_chat_conversations(self, user_id: str) -> int:
        """Live chat conversations that would be reset by ``reset_memory_synced_at_for_user``."""
        result = await self._session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
                Conversation.mode == "chat",
                Conversation.memory_synced_at.isnot(None),
            )
        )
        return int(result.scalar_one())

    async def set_compaction(
        self,
        conversation_id: str,
        *,
        summary: str,
        compacted_through: datetime,
        input_tokens: int | None,
    ) -> None:
        """Persist the rolling compaction summary + its watermark (执行引擎 §三 长对话压缩).

        ``summary`` is the merged rolling digest, ``compacted_through`` the created_at
        of the last message folded into it (the loader replays only messages strictly
        newer than this), and ``input_tokens`` the turn-input size that triggered this
        (re)compaction — observability for tuning the threshold. Written once per fold
        by the off-turn background pass (conversation/compaction.py); reused verbatim
        across turns so the DeepSeek exact-prefix cache holds.
        """
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                compaction_summary=summary,
                compacted_through=compacted_through,
                compaction_input_tokens=input_tokens,
            )
        )
        await self._session.commit()

    async def list_pending_memory_consolidation(
        self, *, idle_before: datetime, limit: int
    ) -> Sequence[str]:
        """Ids of settled chats that have un-consolidated messages (sweeper work list).

        A conversation qualifies when its latest message is newer than its
        ``memory_synced_at`` watermark (有未整合的新内容) yet is at/older than
        ``idle_before`` (已静默, the debounce window has elapsed). Restricted to
        normal chats — hidden handoff hosts (P2e) carry agent runs, not user talk.
        Oldest-settled first, capped by ``limit``. Backs the periodic backstop that
        covers a debounce dropped by a restart / closed client.
        """
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        last_msg = func.max(Message.created_at)
        result = await self._session.execute(
            select(Conversation.id)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                Conversation.deleted_at.is_(None),
                Conversation.mode == "chat",
            )
            .group_by(Conversation.id, Conversation.memory_synced_at)
            .having(
                and_(
                    last_msg > func.coalesce(Conversation.memory_synced_at, epoch),
                    last_msg <= idle_before,
                )
            )
            .order_by(last_msg.asc())
            .limit(limit)
        )
        return [row[0] for row in result.all()]

    async def list_all_by_user(self, user_id: str) -> Sequence[Conversation]:
        """Every live (non-archived) conversation for a user, pinned-first then
        newest activity.

        Unpaginated — backs the folder-grouped sidebar, which groups the full
        set client-side (the flat list is small in the desktop MVP). Archived
        conversations are excluded here (they live in the separate「已归档」view);
        pinned ones sort to the top (置顶对话).
        """
        result = await self._session.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
                # Hidden handoff-job conversations (P2e / e2) are not sidebar chats.
                Conversation.mode != "handoff",
                # Archived chats are hidden from the live list (归档对话, reversible).
                Conversation.archived.is_(False),
            )
            .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
        )
        return result.scalars().all()

    async def set_local_binding(
        self, conversation_id: str, *, root_id: str | None, subpath: str | None = None
    ) -> None:
        """Set the conversation's scratch workspace local binding."""
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(local_root_id=root_id, local_subpath=subpath)
        )
        await self._session.commit()
