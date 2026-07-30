"""Product notices data access (全局 Notice)."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models.notices import ProductNoticeDismissalRow, ProductNoticeRow

_SEVERITY_RANK = {"critical": 0, "high": 1, "normal": 2}


def _sort_key(row: ProductNoticeRow) -> tuple:
    """severity (critical>high>normal) then published_at newest-first."""
    sev = _SEVERITY_RANK.get(row.severity, 99)
    pub = row.published_at or datetime.min.replace(tzinfo=UTC)
    return (sev, -pub.timestamp())


class ProductNoticeRepository:
    """Admin CRUD + user active/dismiss for product notices."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        title: str,
        body: str,
        severity: str,
        surface: str,
        dismiss_policy: str,
        created_by: str,
        cta_label: str | None = None,
        cta_url: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        status: str = "draft",
    ) -> ProductNoticeRow:
        row = ProductNoticeRow(
            title=title,
            body=body,
            severity=severity,
            surface=surface,
            dismiss_policy=dismiss_policy,
            created_by=created_by,
            cta_label=cta_label,
            cta_url=cta_url,
            start_at=start_at,
            end_at=end_at,
            status=status,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get(self, notice_id: str) -> ProductNoticeRow | None:
        result = await self._session.execute(
            select(ProductNoticeRow).where(ProductNoticeRow.id == notice_id)
        )
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[ProductNoticeRow], int]:
        base = select(ProductNoticeRow)
        count_base = select(func.count()).select_from(ProductNoticeRow)
        if status:
            base = base.where(ProductNoticeRow.status == status)
            count_base = count_base.where(ProductNoticeRow.status == status)

        total_result = await self._session.execute(count_base)
        total = total_result.scalar() or 0

        result = await self._session.execute(
            base.order_by(ProductNoticeRow.created_at.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all(), total

    async def update(
        self,
        notice_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        severity: str | None = None,
        surface: str | None = None,
        dismiss_policy: str | None = None,
        cta_label: str | None | object = ...,
        cta_url: str | None | object = ...,
        start_at: datetime | None | object = ...,
        end_at: datetime | None | object = ...,
    ) -> ProductNoticeRow | None:
        values: dict = {}
        if title is not None:
            values["title"] = title
        if body is not None:
            values["body"] = body
        if severity is not None:
            values["severity"] = severity
        if surface is not None:
            values["surface"] = surface
        if dismiss_policy is not None:
            values["dismiss_policy"] = dismiss_policy
        if cta_label is not ...:
            values["cta_label"] = cta_label
        if cta_url is not ...:
            values["cta_url"] = cta_url
        if start_at is not ...:
            values["start_at"] = start_at
        if end_at is not ...:
            values["end_at"] = end_at
        if not values:
            return await self.get(notice_id)

        stmt = (
            update(ProductNoticeRow)
            .where(ProductNoticeRow.id == notice_id)
            .values(**values)
            .returning(ProductNoticeRow)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.scalar_one_or_none()

    async def publish(self, notice_id: str) -> ProductNoticeRow | None:
        now = datetime.now(UTC)
        stmt = (
            update(ProductNoticeRow)
            .where(ProductNoticeRow.id == notice_id)
            .values(status="published", published_at=now)
            .returning(ProductNoticeRow)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.scalar_one_or_none()

    async def archive(self, notice_id: str) -> ProductNoticeRow | None:
        stmt = (
            update(ProductNoticeRow)
            .where(ProductNoticeRow.id == notice_id)
            .values(status="archived")
            .returning(ProductNoticeRow)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.scalar_one_or_none()

    async def list_active_published(
        self, *, now: datetime | None = None
    ) -> Sequence[ProductNoticeRow]:
        """Published notices currently inside their optional time window."""
        now = now or datetime.now(UTC)
        in_window = and_(
            or_(ProductNoticeRow.start_at.is_(None), ProductNoticeRow.start_at <= now),
            or_(ProductNoticeRow.end_at.is_(None), ProductNoticeRow.end_at >= now),
        )
        result = await self._session.execute(
            select(ProductNoticeRow).where(
                ProductNoticeRow.status == "published",
                in_window,
            )
        )
        rows = list(result.scalars().all())
        rows.sort(key=_sort_key)
        return rows

    async def list_dismissed_ids(self, user_id: str, notice_ids: Sequence[str]) -> set[str]:
        if not notice_ids:
            return set()
        result = await self._session.execute(
            select(ProductNoticeDismissalRow.notice_id).where(
                ProductNoticeDismissalRow.user_id == user_id,
                ProductNoticeDismissalRow.notice_id.in_(list(notice_ids)),
            )
        )
        return set(result.scalars().all())

    async def is_dismissed(self, notice_id: str, user_id: str) -> bool:
        result = await self._session.execute(
            select(ProductNoticeDismissalRow.notice_id).where(
                ProductNoticeDismissalRow.notice_id == notice_id,
                ProductNoticeDismissalRow.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def dismiss(self, notice_id: str, user_id: str) -> None:
        """Insert dismissal; no-op if already present (idempotent)."""
        stmt = (
            pg_insert(ProductNoticeDismissalRow)
            .values(notice_id=notice_id, user_id=user_id)
            .on_conflict_do_nothing(index_elements=["notice_id", "user_id"])
        )
        await self._session.execute(stmt)
        await self._session.commit()
