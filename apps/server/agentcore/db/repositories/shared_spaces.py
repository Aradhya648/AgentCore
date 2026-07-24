"""Shared space data access: spaces, members, change events."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models.shared_spaces import SharedSpace, SharedSpaceEvent, SharedSpaceMember


class SharedSpaceRepository:
    """Membership-scoped data access for the shared-space domain.

    Authorization (non-member → 404) lives in the service layer; this repo only
    reads/writes rows. Independent of owner-scope folder/conversation repos.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    # --- Spaces ---

    async def create_space(self, *, owner_user_id: str, name: str) -> SharedSpace:
        space = SharedSpace(id=new_id(), owner_user_id=owner_user_id, name=name)
        self._session.add(space)
        self._session.add(
            SharedSpaceMember(
                space_id=space.id,
                user_id=owner_user_id,
                role="owner",
                state="accepted",
                invited_by=None,
            )
        )
        await self._session.commit()
        await self._session.refresh(space)
        return space

    async def get_space(self, space_id: str) -> SharedSpace | None:
        result = await self._session.execute(
            select(SharedSpace).where(SharedSpace.id == space_id)
        )
        return result.scalar_one_or_none()

    async def update_space(self, space_id: str, *, name: str) -> SharedSpace | None:
        space = await self.get_space(space_id)
        if space is None:
            return None
        space.name = name
        await self._session.commit()
        await self._session.refresh(space)
        return space

    async def delete_space(self, space_id: str) -> bool:
        space = await self.get_space(space_id)
        if space is None:
            return False
        await self._session.execute(
            delete(SharedSpaceEvent).where(SharedSpaceEvent.space_id == space_id)
        )
        await self._session.execute(
            delete(SharedSpaceMember).where(SharedSpaceMember.space_id == space_id)
        )
        await self._session.execute(delete(SharedSpace).where(SharedSpace.id == space_id))
        await self._session.commit()
        return True

    async def count_owned_spaces(self, owner_user_id: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(SharedSpace)
            .where(SharedSpace.owner_user_id == owner_user_id)
        )
        return int(result.scalar_one())

    async def list_spaces_for_user(
        self, user_id: str, *, state: str = "accepted"
    ) -> Sequence[tuple[SharedSpace, SharedSpaceMember]]:
        result = await self._session.execute(
            select(SharedSpace, SharedSpaceMember)
            .join(
                SharedSpaceMember,
                SharedSpaceMember.space_id == SharedSpace.id,
            )
            .where(
                SharedSpaceMember.user_id == user_id,
                SharedSpaceMember.state == state,
            )
            .order_by(SharedSpace.updated_at.desc())
        )
        return result.all()

    async def list_owned_space_ids(self, owner_user_id: str) -> Sequence[str]:
        result = await self._session.execute(
            select(SharedSpace.id).where(SharedSpace.owner_user_id == owner_user_id)
        )
        return list(result.scalars().all())

    # --- Members ---

    async def get_member(self, space_id: str, user_id: str) -> SharedSpaceMember | None:
        result = await self._session.execute(
            select(SharedSpaceMember).where(
                SharedSpaceMember.space_id == space_id,
                SharedSpaceMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_members(self, space_id: str) -> Sequence[SharedSpaceMember]:
        result = await self._session.execute(
            select(SharedSpaceMember)
            .where(SharedSpaceMember.space_id == space_id)
            .order_by(SharedSpaceMember.joined_at.asc())
        )
        return result.scalars().all()

    async def count_members(self, space_id: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(SharedSpaceMember)
            .where(SharedSpaceMember.space_id == space_id)
        )
        return int(result.scalar_one())

    async def add_member(
        self,
        *,
        space_id: str,
        user_id: str,
        role: str,
        state: str,
        invited_by: str | None,
    ) -> SharedSpaceMember:
        member = SharedSpaceMember(
            space_id=space_id,
            user_id=user_id,
            role=role,
            state=state,
            invited_by=invited_by,
        )
        self._session.add(member)
        await self._session.commit()
        await self._session.refresh(member)
        return member

    async def set_member_state(self, space_id: str, user_id: str, *, state: str) -> None:
        await self._session.execute(
            update(SharedSpaceMember)
            .where(
                SharedSpaceMember.space_id == space_id,
                SharedSpaceMember.user_id == user_id,
            )
            .values(state=state)
        )
        await self._session.commit()

    async def set_member_role(self, space_id: str, user_id: str, *, role: str) -> None:
        await self._session.execute(
            update(SharedSpaceMember)
            .where(
                SharedSpaceMember.space_id == space_id,
                SharedSpaceMember.user_id == user_id,
            )
            .values(role=role)
        )
        await self._session.commit()

    async def remove_member(self, space_id: str, user_id: str) -> None:
        await self._session.execute(
            delete(SharedSpaceMember).where(
                SharedSpaceMember.space_id == space_id,
                SharedSpaceMember.user_id == user_id,
            )
        )
        await self._session.commit()

    async def list_pending_for_user(
        self, user_id: str
    ) -> Sequence[tuple[SharedSpace, SharedSpaceMember]]:
        result = await self._session.execute(
            select(SharedSpace, SharedSpaceMember)
            .join(
                SharedSpaceMember,
                SharedSpaceMember.space_id == SharedSpace.id,
            )
            .where(
                SharedSpaceMember.user_id == user_id,
                SharedSpaceMember.state == "pending",
            )
            .order_by(SharedSpaceMember.joined_at.desc())
        )
        return result.all()

    async def delete_pending_between(self, user_a: str, user_b: str) -> int:
        """Auto-reject pending invites between a blocked pair (either direction).

        Covers: A invited B (pending on B, invited_by=A) and B invited A.
        Returns the number of rows removed.
        """
        # Pending rows where one is invitee and the other is inviter.
        result = await self._session.execute(
            select(SharedSpaceMember).where(
                SharedSpaceMember.state == "pending",
                (
                    (
                        (SharedSpaceMember.user_id == user_a)
                        & (SharedSpaceMember.invited_by == user_b)
                    )
                    | (
                        (SharedSpaceMember.user_id == user_b)
                        & (SharedSpaceMember.invited_by == user_a)
                    )
                ),
            )
        )
        rows = list(result.scalars().all())
        for row in rows:
            await self._session.delete(row)
        if rows:
            await self._session.commit()
        return len(rows)

    async def delete_all_memberships_for_user(self, user_id: str) -> Sequence[str]:
        """Remove every membership row for ``user_id``; return affected space ids."""
        result = await self._session.execute(
            select(SharedSpaceMember.space_id).where(SharedSpaceMember.user_id == user_id)
        )
        space_ids = list(result.scalars().all())
        await self._session.execute(
            delete(SharedSpaceMember).where(SharedSpaceMember.user_id == user_id)
        )
        await self._session.commit()
        return space_ids

    # --- Events ---

    async def add_event(
        self,
        *,
        space_id: str,
        actor_user_id: str | None,
        actor_via: str,
        action: str,
        path: str | None = None,
        detail: dict | None = None,
    ) -> SharedSpaceEvent:
        event = SharedSpaceEvent(
            id=new_id(),
            space_id=space_id,
            actor_user_id=actor_user_id,
            actor_via=actor_via,
            action=action,
            path=path,
            detail=detail,
        )
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return event

    async def list_events(
        self, space_id: str, *, limit: int = 50, before_id: str | None = None
    ) -> Sequence[SharedSpaceEvent]:
        stmt = (
            select(SharedSpaceEvent)
            .where(SharedSpaceEvent.space_id == space_id)
            .order_by(SharedSpaceEvent.created_at.desc())
            .limit(limit)
        )
        if before_id:
            pivot = await self._session.execute(
                select(SharedSpaceEvent).where(SharedSpaceEvent.id == before_id)
            )
            row = pivot.scalar_one_or_none()
            if row is not None:
                stmt = (
                    select(SharedSpaceEvent)
                    .where(
                        SharedSpaceEvent.space_id == space_id,
                        SharedSpaceEvent.created_at < row.created_at,
                    )
                    .order_by(SharedSpaceEvent.created_at.desc())
                    .limit(limit)
                )
        result = await self._session.execute(stmt)
        return result.scalars().all()
