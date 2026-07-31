"""User workflow repository (账户级 CRUD)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models.user_workflows import UserWorkflow
from agentcore.db.repositories._base import strip_nul


class UserWorkflowRepository:
    """Owner-scoped workflow CRUD. ``version`` bumps on every successful update."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        name: str,
        definition: dict,
        description: str | None = None,
    ) -> UserWorkflow:
        row = UserWorkflow(
            id=new_id(),
            user_id=user_id,
            name=strip_nul(name) or "未命名工作流",
            description=strip_nul(description) if description else None,
            definition=dict(definition or {}),
            version=1,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get_by_id(
        self, workflow_id: str, *, user_id: str | None = None
    ) -> UserWorkflow | None:
        conditions = [UserWorkflow.id == workflow_id]
        if user_id is not None:
            conditions.append(UserWorkflow.user_id == user_id)
        result = await self._session.execute(select(UserWorkflow).where(*conditions))
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> Sequence[UserWorkflow]:
        result = await self._session.execute(
            select(UserWorkflow)
            .where(UserWorkflow.user_id == user_id)
            .order_by(UserWorkflow.updated_at.desc())
        )
        return result.scalars().all()

    async def update(
        self,
        workflow_id: str,
        *,
        user_id: str,
        name: str | None = None,
        description: str | None | object = ...,
        definition: dict | None = None,
    ) -> UserWorkflow | None:
        row = await self.get_by_id(workflow_id, user_id=user_id)
        if row is None:
            return None
        bumped = False
        if name is not None:
            row.name = strip_nul(name) or row.name
            bumped = True
        if description is not ...:
            if description is None:
                row.description = None
            else:
                row.description = strip_nul(str(description)) or None
            bumped = True
        if definition is not None:
            row.definition = dict(definition)
            bumped = True
        if bumped:
            row.version = int(row.version or 1) + 1
            row.updated_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(row)
        return row

    async def delete(self, workflow_id: str, *, user_id: str) -> bool:
        row = await self.get_by_id(workflow_id, user_id=user_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True
