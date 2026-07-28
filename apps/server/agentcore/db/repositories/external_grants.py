"""Data access for conversation-scoped external directory grants (W3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models import ConversationExternalGrant


class ExternalGrantRepository:
    """CRUD for ``conversation_external_grants`` (app-level conversation ownership)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_conversation(
        self, conversation_id: str
    ) -> Sequence[ConversationExternalGrant]:
        result = await self._session.execute(
            select(ConversationExternalGrant)
            .where(ConversationExternalGrant.conversation_id == conversation_id)
            .order_by(ConversationExternalGrant.created_at.asc())
        )
        return result.scalars().all()

    async def upsert(
        self,
        *,
        conversation_id: str,
        root_id: str,
        alias: str,
        label: str,
        mode: str,
    ) -> ConversationExternalGrant:
        """Insert or refresh by ``root_id`` (alias stable on same root)."""
        result = await self._session.execute(
            select(ConversationExternalGrant).where(
                ConversationExternalGrant.conversation_id == conversation_id,
                ConversationExternalGrant.root_id == root_id,
            )
        )
        row = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if row is not None:
            row.label = label or row.label
            row.mode = mode
            row.updated_at = now
            await self._session.commit()
            await self._session.refresh(row)
            return row

        row = ConversationExternalGrant(
            id=new_id(),
            conversation_id=conversation_id,
            alias=alias,
            root_id=root_id,
            label=label or alias,
            mode=mode,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def delete_one(
        self,
        conversation_id: str,
        *,
        alias: str | None = None,
        root_id: str | None = None,
    ) -> int:
        """Delete matching rows; return number removed."""
        stmt = delete(ConversationExternalGrant).where(
            ConversationExternalGrant.conversation_id == conversation_id
        )
        if alias is not None:
            stmt = stmt.where(ConversationExternalGrant.alias == alias)
        if root_id is not None:
            stmt = stmt.where(ConversationExternalGrant.root_id == root_id)
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    async def clear_conversation(self, conversation_id: str) -> None:
        await self._session.execute(
            delete(ConversationExternalGrant).where(
                ConversationExternalGrant.conversation_id == conversation_id
            )
        )
        await self._session.commit()
