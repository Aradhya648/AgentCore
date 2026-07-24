"""User feedback data access (内测反馈)."""

from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models.feedback import FeedbackRow


class FeedbackRepository:
    """Feedback CRUD for beta-testing users."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        category: str,
        title: str,
        description: str,
        page_context: str | None = None,
    ) -> FeedbackRow:
        row = FeedbackRow(
            user_id=user_id,
            category=category,
            title=title,
            description=description,
            page_context=page_context,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def list_by_user(
        self, user_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[Sequence[FeedbackRow], int]:
        total_result = await self._session.execute(
            select(func.count()).select_from(FeedbackRow).where(FeedbackRow.user_id == user_id)
        )
        total = total_result.scalar() or 0

        result = await self._session.execute(
            select(FeedbackRow)
            .where(FeedbackRow.user_id == user_id)
            .order_by(FeedbackRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all(), total

    async def list_all(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[FeedbackRow], int]:
        """Admin: list all feedback with optional filters."""
        base = select(FeedbackRow)
        count_base = select(func.count()).select_from(FeedbackRow)

        if status:
            base = base.where(FeedbackRow.status == status)
            count_base = count_base.where(FeedbackRow.status == status)
        if category:
            base = base.where(FeedbackRow.category == category)
            count_base = count_base.where(FeedbackRow.category == category)

        total_result = await self._session.execute(count_base)
        total = total_result.scalar() or 0

        result = await self._session.execute(
            base.order_by(FeedbackRow.created_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all(), total

    async def update_status(
        self, feedback_id: str, *, status: str, admin_reply: str | None = None
    ) -> FeedbackRow | None:
        extra = {"admin_reply": admin_reply} if admin_reply is not None else {}
        stmt = (
            update(FeedbackRow)
            .where(FeedbackRow.id == feedback_id)
            .values(status=status, **extra)
            .returning(FeedbackRow)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.scalar_one_or_none()
