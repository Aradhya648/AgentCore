"""Friendships and friend requests (消息IM.md §九)."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models import FriendRequest, Friendship


def friendship_pair(user_a: str, user_b: str) -> tuple[str, str]:
    """Canonical order for ``friendships`` (user_a_id < user_b_id)."""
    return (user_a, user_b) if user_a < user_b else (user_b, user_a)


def request_pair_key(user_a: str, user_b: str) -> str:
    """Canonical ``min:max`` key for pending-request uniqueness."""
    a, b = friendship_pair(user_a, user_b)
    return f"{a}:{b}"


class FriendRepository:
    """Data access for bidirectional friendships + friend requests."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def are_friends(self, user_a: str, user_b: str) -> bool:
        a, b = friendship_pair(user_a, user_b)
        result = await self._session.execute(
            select(Friendship.user_a_id).where(
                Friendship.user_a_id == a,
                Friendship.user_b_id == b,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_friend_ids(self, user_id: str) -> Sequence[str]:
        result = await self._session.execute(
            select(Friendship.user_a_id, Friendship.user_b_id).where(
                or_(Friendship.user_a_id == user_id, Friendship.user_b_id == user_id)
            )
        )
        out: list[str] = []
        for a, b in result.all():
            out.append(b if a == user_id else a)
        return out

    async def add_friendship(self, user_a: str, user_b: str) -> None:
        a, b = friendship_pair(user_a, user_b)
        stmt = (
            pg_insert(Friendship)
            .values(user_a_id=a, user_b_id=b)
            .on_conflict_do_nothing(index_elements=["user_a_id", "user_b_id"])
        )
        await self._session.execute(stmt)
        await self._session.commit()

    async def remove_friendship(self, user_a: str, user_b: str) -> bool:
        a, b = friendship_pair(user_a, user_b)
        result = await self._session.execute(
            delete(Friendship).where(
                Friendship.user_a_id == a,
                Friendship.user_b_id == b,
            )
        )
        await self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def get_request(self, request_id: str) -> FriendRequest | None:
        result = await self._session.execute(
            select(FriendRequest).where(FriendRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def get_pending_between(self, user_a: str, user_b: str) -> FriendRequest | None:
        result = await self._session.execute(
            select(FriendRequest).where(
                FriendRequest.status == "pending",
                FriendRequest.pair_key == request_pair_key(user_a, user_b),
            )
        )
        return result.scalar_one_or_none()

    async def create_request(
        self,
        *,
        from_user_id: str,
        to_user_id: str,
        message: str | None = None,
    ) -> FriendRequest:
        req = FriendRequest(
            id=new_id(),
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            pair_key=request_pair_key(from_user_id, to_user_id),
            message=message,
            status="pending",
        )
        self._session.add(req)
        await self._session.commit()
        await self._session.refresh(req)
        return req

    async def set_request_status(self, request_id: str, status: str) -> FriendRequest | None:
        result = await self._session.execute(
            select(FriendRequest).where(FriendRequest.id == request_id)
        )
        req = result.scalar_one_or_none()
        if req is None:
            return None
        req.status = status
        req.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(req)
        return req

    async def cancel_pending_between(self, user_a: str, user_b: str) -> list[FriendRequest]:
        """Cancel all pending requests between the pair; return the cancelled rows."""
        result = await self._session.execute(
            select(FriendRequest).where(
                FriendRequest.status == "pending",
                FriendRequest.pair_key == request_pair_key(user_a, user_b),
            )
        )
        pending = list(result.scalars().all())
        if not pending:
            return []
        now = datetime.now(UTC)
        for req in pending:
            req.status = "cancelled"
            req.updated_at = now
        await self._session.commit()
        for req in pending:
            await self._session.refresh(req)
        return pending

    async def list_pending_incoming(self, user_id: str) -> Sequence[FriendRequest]:
        result = await self._session.execute(
            select(FriendRequest)
            .where(
                FriendRequest.to_user_id == user_id,
                FriendRequest.status == "pending",
            )
            .order_by(FriendRequest.created_at.desc())
        )
        return result.scalars().all()

    async def list_pending_outgoing(self, user_id: str) -> Sequence[FriendRequest]:
        result = await self._session.execute(
            select(FriendRequest)
            .where(
                FriendRequest.from_user_id == user_id,
                FriendRequest.status == "pending",
            )
            .order_by(FriendRequest.created_at.desc())
        )
        return result.scalars().all()
