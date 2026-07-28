"""Standing task + run repository (站立任务 / 收件箱 / L2a webhook)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models.standing_tasks import StandingTask, StandingTaskRun

from ._base import strip_nul


def is_lease_free(*, lease_until: datetime | None, now: datetime) -> bool:
    """True when the task lease is absent or expired (safe to claim for dispatch)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if lease_until is None:
        return True
    if lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=UTC)
    return lease_until < now


def is_task_claimable(
    *,
    enabled: bool,
    next_run_at: datetime | None,
    lease_until: datetime | None,
    now: datetime,
    trigger_kind: str = "schedule",
) -> bool:
    """Whether a standing task may be claimed by the scheduler (lease anti-double-run).

    Webhook tasks are never claimable by the schedule poll.
    """
    if trigger_kind != "schedule":
        return False
    if not enabled:
        return False
    if next_run_at is None:
        return False
    if next_run_at.tzinfo is None:
        next_run_at = next_run_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if next_run_at > now:
        return False
    return is_lease_free(lease_until=lease_until, now=now)


class StandingTaskRepository:
    """Owner-scoped standing task CRUD + scheduler lease claims."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: str,
        folder_id: str,
        name: str,
        goal: str,
        cron: str | None,
        permission_axes: dict,
        next_run_at: datetime | None,
        enabled: bool = True,
        trigger_kind: str = "schedule",
        webhook_id: str | None = None,
        webhook_secret_hash: str | None = None,
    ) -> StandingTask:
        row = StandingTask(
            id=new_id(),
            user_id=user_id,
            folder_id=folder_id,
            name=strip_nul(name) or "未命名站立任务",
            goal=strip_nul(goal),
            cron=cron,
            permission_axes=permission_axes,
            enabled=enabled,
            next_run_at=next_run_at,
            trigger_kind=trigger_kind,
            webhook_id=webhook_id,
            webhook_secret_hash=webhook_secret_hash,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get_by_id(self, task_id: str, *, user_id: str | None = None) -> StandingTask | None:
        conditions = [StandingTask.id == task_id]
        if user_id is not None:
            conditions.append(StandingTask.user_id == user_id)
        result = await self._session.execute(select(StandingTask).where(*conditions))
        return result.scalar_one_or_none()

    async def get_by_webhook_id(self, webhook_id: str) -> StandingTask | None:
        result = await self._session.execute(
            select(StandingTask).where(
                StandingTask.webhook_id == webhook_id,
                StandingTask.trigger_kind == "webhook",
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str) -> Sequence[StandingTask]:
        result = await self._session.execute(
            select(StandingTask)
            .where(StandingTask.user_id == user_id)
            .order_by(StandingTask.created_at.desc())
        )
        return result.scalars().all()

    async def update(
        self,
        task_id: str,
        *,
        user_id: str,
        **fields: object,
    ) -> StandingTask | None:
        row = await self.get_by_id(task_id, user_id=user_id)
        if row is None:
            return None
        for key, value in fields.items():
            if key in {"name", "goal"} and isinstance(value, str):
                value = strip_nul(value)
            setattr(row, key, value)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def delete(self, task_id: str, *, user_id: str) -> bool:
        row = await self.get_by_id(task_id, user_id=user_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True

    async def attach_conversation(
        self, task_id: str, *, conversation_id: str
    ) -> StandingTask | None:
        """Bind the pinned conversation (first fire). Idempotent if already set."""
        result = await self._session.execute(
            update(StandingTask)
            .where(
                StandingTask.id == task_id,
                StandingTask.conversation_id.is_(None),
            )
            .values(conversation_id=conversation_id)
            .returning(StandingTask)
        )
        row = result.scalar_one_or_none()
        await self._session.commit()
        if row is not None:
            return row
        return await self.get_by_id(task_id)

    async def claim_due(
        self,
        *,
        now: datetime,
        owner: str,
        lease_seconds: int,
        limit: int = 10,
    ) -> list[StandingTask]:
        """Atomically claim up to ``limit`` due enabled *schedule* tasks.

        Claimable when ``trigger_kind=schedule`` and ``enabled`` and
        ``next_run_at <= now`` and lease absent/expired. Webhook rows are skipped.
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        lease_until = datetime.fromtimestamp(now.timestamp() + lease_seconds, tz=UTC)

        candidates = (
            (
                await self._session.execute(
                    select(StandingTask.id)
                    .where(
                        StandingTask.trigger_kind == "schedule",
                        StandingTask.enabled.is_(True),
                        StandingTask.next_run_at.is_not(None),
                        StandingTask.next_run_at <= now,
                        or_(
                            StandingTask.lease_until.is_(None),
                            StandingTask.lease_until < now,
                        ),
                    )
                    .order_by(StandingTask.next_run_at.asc())
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        claimed: list[StandingTask] = []
        for task_id in candidates:
            result = await self._session.execute(
                update(StandingTask)
                .where(
                    StandingTask.id == task_id,
                    StandingTask.trigger_kind == "schedule",
                    StandingTask.enabled.is_(True),
                    StandingTask.next_run_at.is_not(None),
                    StandingTask.next_run_at <= now,
                    or_(
                        StandingTask.lease_until.is_(None),
                        StandingTask.lease_until < now,
                    ),
                )
                .values(
                    lease_owner=owner,
                    lease_until=lease_until,
                    last_run_at=now,
                )
                .returning(StandingTask)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                claimed.append(row)
        await self._session.commit()
        return claimed

    async def advance_next_run(self, task_id: str, *, next_run_at: datetime) -> None:
        await self._session.execute(
            update(StandingTask)
            .where(StandingTask.id == task_id)
            .values(next_run_at=next_run_at)
        )
        await self._session.commit()

    async def touch_last_run(self, task_id: str, *, at: datetime | None = None) -> None:
        await self._session.execute(
            update(StandingTask)
            .where(StandingTask.id == task_id)
            .values(last_run_at=at or datetime.now(UTC))
        )
        await self._session.commit()

    async def claim_dispatch(
        self,
        task_id: str,
        *,
        owner: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> StandingTask | None:
        """Atomically claim the task lease for webhook / manual dispatch.

        Returns the row when claimed; ``None`` when another owner still holds
        an unexpired lease (in-flight). Reuses the same ``lease_owner`` /
        ``lease_until`` columns as ``claim_due`` — no parallel mutex layer.
        """
        if now is None:
            now = datetime.now(UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        lease_until = datetime.fromtimestamp(now.timestamp() + lease_seconds, tz=UTC)
        result = await self._session.execute(
            update(StandingTask)
            .where(
                StandingTask.id == task_id,
                or_(
                    StandingTask.lease_until.is_(None),
                    StandingTask.lease_until < now,
                ),
            )
            .values(
                lease_owner=owner,
                lease_until=lease_until,
                last_run_at=now,
            )
            .returning(StandingTask)
        )
        row = result.scalar_one_or_none()
        await self._session.commit()
        return row

    async def clear_lease(self, task_id: str, *, owner: str | None = None) -> None:
        conditions = [StandingTask.id == task_id]
        if owner is not None:
            conditions.append(StandingTask.lease_owner == owner)
        await self._session.execute(
            update(StandingTask)
            .where(*conditions)
            .values(lease_owner=None, lease_until=None)
        )
        await self._session.commit()


class StandingTaskRunRepository:
    """Inbox rows for standing task fires."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        standing_task_id: str,
        user_id: str,
        conversation_id: str | None = None,
        status: str = "running",
        trigger_source: str = "schedule",
    ) -> StandingTaskRun:
        row = StandingTaskRun(
            id=new_id(),
            standing_task_id=standing_task_id,
            user_id=user_id,
            conversation_id=conversation_id,
            status=status,
            trigger_source=trigger_source,
            started_at=datetime.now(UTC),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get_by_id(self, run_id: str, *, user_id: str | None = None) -> StandingTaskRun | None:
        conditions = [StandingTaskRun.id == run_id]
        if user_id is not None:
            conditions.append(StandingTaskRun.user_id == user_id)
        result = await self._session.execute(select(StandingTaskRun).where(*conditions))
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
        unacked_only: bool = False,
    ) -> Sequence[StandingTaskRun]:
        conditions = [StandingTaskRun.user_id == user_id]
        if status is not None:
            conditions.append(StandingTaskRun.status == status)
        if unacked_only:
            conditions.append(StandingTaskRun.acked_at.is_(None))
        result = await self._session.execute(
            select(StandingTaskRun)
            .where(*conditions)
            .order_by(StandingTaskRun.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def set_conversation_and_message(
        self,
        run_id: str,
        *,
        conversation_id: str,
        user_message_id: str,
    ) -> None:
        await self._session.execute(
            update(StandingTaskRun)
            .where(StandingTaskRun.id == run_id)
            .values(conversation_id=conversation_id, user_message_id=user_message_id)
        )
        await self._session.commit()

    async def mark_succeeded(self, run_id: str, *, summary: str | None) -> None:
        await self._session.execute(
            update(StandingTaskRun)
            .where(StandingTaskRun.id == run_id)
            .values(
                status="succeeded",
                summary=strip_nul(summary) if summary else None,
                finished_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def mark_failed(self, run_id: str, *, error: str) -> None:
        await self._session.execute(
            update(StandingTaskRun)
            .where(StandingTaskRun.id == run_id)
            .values(
                status="failed",
                error=strip_nul(error)[:4000],
                finished_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def mark_awaiting_user(self, run_id: str, *, summary: str | None = None) -> None:
        await self._session.execute(
            update(StandingTaskRun)
            .where(StandingTaskRun.id == run_id)
            .values(
                status="awaiting_user",
                summary=strip_nul(summary) if summary else None,
                finished_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def list_awaiting_for_conversation(
        self, conversation_id: str
    ) -> Sequence[StandingTaskRun]:
        """Open awaiting_user inbox rows pinned to a standing conversation."""
        result = await self._session.execute(
            select(StandingTaskRun)
            .where(
                StandingTaskRun.conversation_id == conversation_id,
                StandingTaskRun.status == "awaiting_user",
            )
            .order_by(StandingTaskRun.created_at.desc())
        )
        return result.scalars().all()

    async def ack(self, run_id: str, *, user_id: str) -> StandingTaskRun | None:
        """Mark an inbox row acknowledged (read / dismiss failure / dismiss await).

        Owner-scoped. Applies to any terminal status including ``awaiting_user``
        (badge counts only unacked awaiting_user + failed).
        """
        result = await self._session.execute(
            update(StandingTaskRun)
            .where(
                StandingTaskRun.id == run_id,
                StandingTaskRun.user_id == user_id,
                StandingTaskRun.acked_at.is_(None),
            )
            .values(acked_at=datetime.now(UTC))
            .returning(StandingTaskRun)
        )
        row = result.scalar_one_or_none()
        await self._session.commit()
        if row is not None:
            return row
        return await self.get_by_id(run_id, user_id=user_id)

    async def count_badge(self, user_id: str) -> int:
        """Unacked awaiting_user + unacked failed for nav badge."""
        result = await self._session.execute(
            select(func.count())
            .select_from(StandingTaskRun)
            .where(
                StandingTaskRun.user_id == user_id,
                StandingTaskRun.acked_at.is_(None),
                StandingTaskRun.status.in_(("awaiting_user", "failed")),
            )
        )
        return int(result.scalar_one() or 0)
