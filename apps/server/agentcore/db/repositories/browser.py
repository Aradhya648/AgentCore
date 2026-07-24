"""L3 团队浏览器 M2 接管留档数据访问（内置浏览器与Agent浏览器提案.md · D17）.

Pure storage for ``browser_takeovers`` (see the model for lifecycle). Three ops:
:meth:`create` inserts an in-progress episode, :meth:`finalize` closes one idempotently
(so any of the many end paths — or a duplicate — writes at most one completion), and
:meth:`list_for_conversation` serves the owner's timeline. No frame / key / text content
ever touches this layer (D17).
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models import BrowserTakeoverRow


class BrowserTakeoverRepository:
    """Data access for user-takeover audit records (owner-scoped by conversation)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, conversation_id: str, user_id: str) -> tuple[str, datetime]:
        """Insert an in-progress takeover episode; return ``(record_id, started_at)``."""
        started_at = datetime.now(UTC)
        row = BrowserTakeoverRow(
            id=new_id(),
            conversation_id=conversation_id,
            user_id=user_id,
            started_at=started_at,
        )
        self._session.add(row)
        await self._session.commit()
        return row.id, started_at

    async def finalize(self, *, record_id: str, reason: str) -> bool:
        """Stamp ``ended_at`` + ``end_reason`` on an OPEN episode (idempotent).

        The ``ended_at IS NULL`` guard makes a second call (e.g. a drop path racing an
        explicit end) a no-op, so an episode is completed exactly once. Returns whether a
        row was closed by THIS call.
        """
        result = await self._session.execute(
            update(BrowserTakeoverRow)
            .where(
                BrowserTakeoverRow.id == record_id,
                BrowserTakeoverRow.ended_at.is_(None),
            )
            .values(ended_at=datetime.now(UTC), end_reason=(reason or "")[:40])
        )
        await self._session.commit()
        return (result.rowcount or 0) > 0

    async def list_for_conversation(
        self, conversation_id: str
    ) -> Sequence[BrowserTakeoverRow]:
        """One conversation's takeover episodes, newest-first (timeline card)."""
        result = await self._session.execute(
            select(BrowserTakeoverRow)
            .where(BrowserTakeoverRow.conversation_id == conversation_id)
            .order_by(BrowserTakeoverRow.started_at.desc())
        )
        return result.scalars().all()
