"""Folder (项目 = 工作区) data access."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models import Board, Conversation, Folder

from ._base import _ilike_pattern


class FolderRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        name: str,
        local_root_id: str | None = None,
        local_subpath: str | None = None,
    ) -> Folder:
        """Create a project workspace.

        ``local_root_id`` set → local project; both binding columns NULL → cloud
        project (shared ``folder:<id>`` scope). Binding is immutable after create.
        """
        folder = Folder(
            id=new_id(),
            user_id=user_id,
            name=name,
            local_root_id=local_root_id,
            local_subpath=local_subpath,
        )
        self._session.add(folder)
        await self._session.commit()
        await self._session.refresh(folder)
        return folder

    async def get_by_id(self, folder_id: str, *, user_id: str) -> Folder | None:
        """Owner-scoped fetch (non-owner / unknown id → None → route 404). ``user_id``
        mandatory so scoping is the structural default (SEC-002); trusted internal callers
        use :meth:`get_by_id_unscoped`."""
        result = await self._session.execute(
            select(Folder).where(
                Folder.id == folder_id,
                Folder.deleted_at.is_(None),
                Folder.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_unscoped(self, folder_id: str) -> Folder | None:
        """Cross-owner fetch for trusted internal callers resolving a conversation's own
        folder (already authorized via that conversation). The explicit name keeps the
        unscoped surface greppable (SEC-002)."""
        result = await self._session.execute(
            select(Folder).where(Folder.id == folder_id, Folder.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> Sequence[Folder]:
        """A user's live folders, in creation order (sidebar group order)."""
        result = await self._session.execute(
            select(Folder)
            .where(Folder.user_id == user_id, Folder.deleted_at.is_(None))
            .order_by(Folder.created_at.asc())
        )
        return result.scalars().all()

    async def search(
        self,
        user_id: str,
        query: str,
        *,
        limit: int,
        updated_after: datetime | None = None,
    ) -> Sequence[Folder]:
        """Owner-scoped folder-name substring search (全局搜索 Tier 1)."""
        stmt = select(Folder).where(
            Folder.user_id == user_id,
            Folder.deleted_at.is_(None),
            Folder.name.ilike(_ilike_pattern(query)),
        )
        if updated_after is not None:
            stmt = stmt.where(Folder.updated_at >= updated_after)
        result = await self._session.execute(
            stmt.order_by(Folder.updated_at.desc()).limit(limit)
        )
        return result.scalars().all()

    async def update(
        self,
        folder_id: str,
        *,
        user_id: str,
        name: str | None = None,
    ) -> Folder | None:
        """Rename only — workspace binding is immutable after create."""
        folder = await self.get_by_id(folder_id, user_id=user_id)
        if not folder:
            return None
        if name is not None:
            folder.name = name
        await self._session.commit()
        await self._session.refresh(folder)
        return folder

    async def soft_delete(self, folder_id: str, *, user_id: str) -> bool:
        """Soft-delete a project; archive its conversations (keep ``folder_id``).

        Conversations are archived in place — not ungrouped — so project membership
        survives soft-delete. Boards fall back to ungrouped (boards are not sessions).
        """
        folder = await self.get_by_id(folder_id, user_id=user_id)
        if not folder:
            return False
        folder.deleted_at = datetime.now()
        await self._session.execute(
            update(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.folder_id == folder_id,
            )
            .values(archived=True)
        )
        await self._session.execute(
            update(Board)
            .where(Board.user_id == user_id, Board.folder_id == folder_id)
            .values(folder_id=None)
        )
        await self._session.commit()
        return True

    async def list_purgeable(self, *, before: datetime, limit: int) -> Sequence[Folder]:
        """Soft-deleted folders whose ``deleted_at`` is at/older than ``before``."""
        result = await self._session.execute(
            select(Folder)
            .where(Folder.deleted_at.is_not(None), Folder.deleted_at <= before)
            .order_by(Folder.deleted_at.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def hard_delete(self, folder_id: str) -> None:
        """Physically remove a folder record."""
        await self._session.execute(delete(Folder).where(Folder.id == folder_id))
        await self._session.commit()
