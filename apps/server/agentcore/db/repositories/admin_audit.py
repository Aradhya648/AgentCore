"""Admin audit log data access (append-only operator action trail)."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models import AdminAuditLog, User


class AdminAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AdminAuditLog:
        row = AdminAuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def list_page(
        self,
        *,
        page: int,
        page_size: int,
        action: str | None = None,
        actor_id: str | None = None,
    ) -> tuple[list[tuple[AdminAuditLog, str]], int]:
        """One page of audit rows + each actor's current username, newest first."""
        filters = []
        if action is not None:
            filters.append(AdminAuditLog.action == action)
        if actor_id is not None:
            filters.append(AdminAuditLog.actor_id == actor_id)

        count_stmt = select(func.count()).select_from(AdminAuditLog)
        if filters:
            count_stmt = count_stmt.where(*filters)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        offset = (page - 1) * page_size
        stmt = (
            select(AdminAuditLog, User.username)
            .join(User, User.user_id == AdminAuditLog.actor_id)
            .order_by(AdminAuditLog.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        if filters:
            stmt = stmt.where(*filters)

        rows = (await self._session.execute(stmt)).all()
        return [(log, username) for log, username in rows], total
