"""Push notification device token data access (原生推送设备)."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models import PushDeviceRow


class PushDeviceRepository:
    """Push device tokens for native notifications (原生推送设备, 认证与会话 §十)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, *, user_id: str, token: str, platform: str) -> None:
        """Register (or move) a device token to ``user_id``.

        Upsert on ``token`` (its unique key): a token re-registered after rotation, or
        the same physical device logging in as another account, is REASSIGNED to the
        current user rather than duplicated — so a token is owned by exactly one user
        and a stale owner can never receive the new user's pushes.
        """
        now = datetime.now(UTC)
        stmt = (
            pg_insert(PushDeviceRow)
            .values(
                id=str(uuid4()),
                user_id=user_id,
                token=token,
                platform=platform,
            )
            .on_conflict_do_update(
                index_elements=["token"],
                set_={"user_id": user_id, "platform": platform, "updated_at": now},
            )
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def list_by_user(self, user_id: str) -> Sequence[PushDeviceRow]:
        """A user's registered devices, newest-first (设备管理 / 测试用)."""
        result = await self._session.execute(
            select(PushDeviceRow)
            .where(PushDeviceRow.user_id == user_id)
            .order_by(PushDeviceRow.created_at.desc())
        )
        return result.scalars().all()

    async def tokens_for_user(self, user_id: str) -> list[str]:
        """Just the token strings for a user — the push fan-out read path."""
        result = await self._session.execute(
            select(PushDeviceRow.token).where(PushDeviceRow.user_id == user_id)
        )
        return list(result.scalars().all())

    async def delete(self, *, user_id: str, token: str) -> bool:
        """Unregister one token, scoped to its owner (logout). True if a row was removed.

        The ``user_id`` guard makes this idempotent and non-cross-tenant: a user can
        only delete their own token, never evict another account's device.
        """
        result = await self._session.execute(
            delete(PushDeviceRow).where(
                PushDeviceRow.token == token, PushDeviceRow.user_id == user_id
            )
        )
        await self._session.commit()
        return (result.rowcount or 0) > 0

    async def delete_tokens(self, tokens: Sequence[str]) -> None:
        """Prune tokens FCM reported as stale/unregistered (push.notify hygiene)."""
        if not tokens:
            return
        await self._session.execute(
            delete(PushDeviceRow).where(PushDeviceRow.token.in_(list(tokens)))
        )
        await self._session.commit()
