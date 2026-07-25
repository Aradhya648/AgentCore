"""Repository for ``llm_model_profiles`` (模型组合)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db.models import LlmModelProfile
from agentcore.db.repositories._base import _UNSET


class LlmModelProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, profile_id: str, *, user_id: str) -> LlmModelProfile | None:
        result = await self._session.execute(
            select(LlmModelProfile).where(
                LlmModelProfile.id == profile_id,
                LlmModelProfile.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, profile_id: str) -> LlmModelProfile | None:
        result = await self._session.execute(
            select(LlmModelProfile).where(LlmModelProfile.id == profile_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: str, *, include_implicit: bool = False
    ) -> Sequence[LlmModelProfile]:
        stmt = select(LlmModelProfile).where(LlmModelProfile.user_id == user_id)
        if not include_implicit:
            stmt = stmt.where(LlmModelProfile.kind == "user")
        stmt = stmt.order_by(LlmModelProfile.created_at.asc())
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        *,
        user_id: str,
        name: str,
        kind: str = "user",
        main_origin: str,
        main_provider_id: str | None,
        main_model: str,
        worker_origin: str | None = None,
        worker_provider_id: str | None = None,
        worker_model: str | None = None,
        background_origin: str | None = None,
        background_provider_id: str | None = None,
        background_model: str | None = None,
    ) -> LlmModelProfile:
        row = LlmModelProfile(
            user_id=user_id,
            name=name,
            kind=kind,
            main_origin=main_origin,
            main_provider_id=main_provider_id,
            main_model=main_model,
            worker_origin=worker_origin,
            worker_provider_id=worker_provider_id,
            worker_model=worker_model,
            background_origin=background_origin,
            background_provider_id=background_provider_id,
            background_model=background_model,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def update(
        self,
        profile_id: str,
        *,
        user_id: str,
        name: str | object = _UNSET,
        main_origin: str | object = _UNSET,
        main_provider_id: str | None | object = _UNSET,
        main_model: str | object = _UNSET,
        worker_origin: str | None | object = _UNSET,
        worker_provider_id: str | None | object = _UNSET,
        worker_model: str | None | object = _UNSET,
        background_origin: str | None | object = _UNSET,
        background_provider_id: str | None | object = _UNSET,
        background_model: str | None | object = _UNSET,
    ) -> LlmModelProfile | None:
        row = await self.get(profile_id, user_id=user_id)
        if row is None:
            return None
        if name is not _UNSET:
            row.name = str(name)
        if main_origin is not _UNSET:
            row.main_origin = str(main_origin)
        if main_provider_id is not _UNSET:
            row.main_provider_id = main_provider_id  # type: ignore[assignment]
        if main_model is not _UNSET:
            row.main_model = str(main_model)
        if worker_origin is not _UNSET:
            row.worker_origin = worker_origin  # type: ignore[assignment]
        if worker_provider_id is not _UNSET:
            row.worker_provider_id = worker_provider_id  # type: ignore[assignment]
        if worker_model is not _UNSET:
            row.worker_model = worker_model  # type: ignore[assignment]
        if background_origin is not _UNSET:
            row.background_origin = background_origin  # type: ignore[assignment]
        if background_provider_id is not _UNSET:
            row.background_provider_id = background_provider_id  # type: ignore[assignment]
        if background_model is not _UNSET:
            row.background_model = background_model  # type: ignore[assignment]
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def delete(self, profile_id: str, *, user_id: str) -> bool:
        result = await self._session.execute(
            delete(LlmModelProfile).where(
                LlmModelProfile.id == profile_id,
                LlmModelProfile.user_id == user_id,
            )
        )
        await self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def delete_all_for_user(self, user_id: str) -> int:
        result = await self._session.execute(
            delete(LlmModelProfile).where(LlmModelProfile.user_id == user_id)
        )
        await self._session.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    async def clear_provider_refs(self, user_id: str, provider_id: str) -> None:
        """Clear worker / background pins that reference a deleted BYOK provider."""
        rows = await self.list_for_user(user_id, include_implicit=True)
        changed = False
        for row in rows:
            if row.worker_provider_id == provider_id:
                row.worker_origin = None
                row.worker_provider_id = None
                row.worker_model = None
                changed = True
            if row.background_provider_id == provider_id:
                row.background_origin = None
                row.background_provider_id = None
                row.background_model = None
                changed = True
        if changed:
            await self._session.commit()

    async def retarget_main_provider(
        self,
        user_id: str,
        *,
        from_provider_id: str,
        to_provider_id: str | None,
        to_model: str | None,
        to_origin: str,
    ) -> None:
        """When a BYOK provider is deleted, retarget profiles that used it as main."""
        values: dict[str, object | None] = {
            "main_provider_id": to_provider_id,
            "main_origin": to_origin,
        }
        if to_model is not None:
            values["main_model"] = to_model
        await self._session.execute(
            update(LlmModelProfile)
            .where(
                LlmModelProfile.user_id == user_id,
                LlmModelProfile.main_provider_id == from_provider_id,
            )
            .values(**values)
        )
        await self._session.commit()
