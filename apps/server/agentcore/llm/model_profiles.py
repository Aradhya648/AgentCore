"""Model combination profiles (模型组合) — CRUD + expand + system presets.

A profile is ``{main, worker?, background?}``. Empty worker / background = follow_main.
System presets are virtual well-known ids pinned to fixed platform model ids
(``5.2`` / ``grok-4.5``); a preset whose model is absent from the live platform
catalog is hidden from list and falls back on expand.

Distinct from scenario ``ProfileParams`` (temperature / rounds) in ``llm/profiles.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.preference import platform_billing_selectable
from agentcore.config import settings
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.db.models import LlmModelProfile
from agentcore.db.repositories import (
    LlmModelProfileRepository,
    UserLlmProviderRepository,
    UserRepository,
)
from agentcore.db.repositories._base import _UNSET
from agentcore.llm.model_metadata import model_metadata_for
from agentcore.llm.profiles import PLATFORM_MODEL_FLASH
from agentcore.llm.resolve import ModelOrigin, ModelSelection

ProfileKind = Literal["system", "user", "implicit"]

# Well-known UUIDs for virtual system presets (not stored in llm_model_profiles).
SYSTEM_PROFILE_52 = "00000000-0000-4000-8000-000000000011"
SYSTEM_PROFILE_GROK = "00000000-0000-4000-8000-000000000012"
SYSTEM_PROFILE_DEFAULT = SYSTEM_PROFILE_52

# profile_id → fixed platform model id (worker / background always follow main).
SYSTEM_PRESETS: dict[str, str] = {
    SYSTEM_PROFILE_52: "5.2",
    SYSTEM_PROFILE_GROK: "grok-4.5",
}


@dataclass(frozen=True)
class ProfileSlot:
    origin: ModelOrigin
    model: str
    provider_id: str | None = None


@dataclass(frozen=True)
class ExpandedProfile:
    """Resolved slots after expand (worker/background None = follow_main)."""

    profile_id: str
    name: str
    kind: ProfileKind
    main: ModelSelection
    worker: ModelSelection | None = None
    background: ModelSelection | None = None


@dataclass(frozen=True)
class ModelProfileView:
    id: str
    name: str
    kind: ProfileKind
    main: ProfileSlot
    worker: ProfileSlot | None = None
    background: ProfileSlot | None = None
    is_default: bool = False


def is_system_profile_id(profile_id: str | None) -> bool:
    return bool(profile_id) and profile_id in SYSTEM_PRESETS


def _system_preset_display_name(model_id: str) -> str:
    return model_metadata_for(model_id).display_name


def _system_preset_available(profile_id: str) -> bool:
    from agentcore.llm.catalog import _platform_model_ids

    model_id = SYSTEM_PRESETS[profile_id]
    return model_id in _platform_model_ids()


def resolve_system_preset_main(profile_id: str) -> ModelSelection:
    """Fixed platform model for a system preset (no keyword ranking)."""
    model_id = SYSTEM_PRESETS[profile_id]
    return ModelSelection(model=model_id, origin="platform", provider_id=None)


def _slot_from_row(
    origin: str | None, model: str | None, provider_id: str | None
) -> ProfileSlot | None:
    model_s = (model or "").strip() or None
    if not model_s:
        return None
    origin_s: ModelOrigin = "platform" if origin == "platform" else "byok"
    return ProfileSlot(
        origin=origin_s,
        model=model_s,
        provider_id=provider_id if origin_s == "byok" else None,
    )


async def _provider_first_fallback(
    session: AsyncSession, user_id: str
) -> ModelSelection:
    """BYOK first provider / keyless platform — no profile expand (avoids recursion)."""
    from agentcore.llm.resolve import _default_chat_provider_row

    row = await _default_chat_provider_row(session, user_id)
    if row is not None:
        model = (row.default_model or "").strip() or PLATFORM_MODEL_FLASH
        return ModelSelection(model=model, origin="byok", provider_id=row.id)
    platform_model = (settings.platform_model or "").strip() or PLATFORM_MODEL_FLASH
    origin: ModelOrigin = "platform" if platform_billing_selectable() else "byok"
    return ModelSelection(model=platform_model, origin=origin, provider_id=None)


async def _live_selection(
    session: AsyncSession,
    user_id: str,
    slot: ProfileSlot,
) -> ModelSelection:
    """Validate a stored slot against live providers / platform gate; silent fallback."""
    from agentcore.llm.resolve import _default_chat_provider_row, _load_provider

    if slot.origin == "platform":
        if not platform_billing_selectable():
            return await _provider_first_fallback(session, user_id)
        return ModelSelection(model=slot.model, origin="platform", provider_id=None)

    if slot.provider_id:
        row = await _load_provider(session, user_id, slot.provider_id)
        if row is not None:
            return ModelSelection(
                model=slot.model, origin="byok", provider_id=row.id
            )
        return await _provider_first_fallback(session, user_id)

    row = await _default_chat_provider_row(session, user_id)
    if row is not None:
        return ModelSelection(model=slot.model, origin="byok", provider_id=row.id)
    return await _provider_first_fallback(session, user_id)


class LlmModelProfileService:
    """CRUD + default + expand for model combination profiles."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = LlmModelProfileRepository(session)
        self._users = UserRepository(session)
        self._providers = UserLlmProviderRepository(session)

    async def _default_id(self, user_id: str) -> str | None:
        user = await self._users.get_by_id(user_id)
        if user is None:
            return None
        return getattr(user, "default_model_profile_id", None)

    def _view_system(self, profile_id: str, *, is_default: bool) -> ModelProfileView:
        model_id = SYSTEM_PRESETS[profile_id]
        main = resolve_system_preset_main(profile_id)
        return ModelProfileView(
            id=profile_id,
            name=_system_preset_display_name(model_id),
            kind="system",
            main=ProfileSlot(
                origin=main.origin, model=main.model, provider_id=main.provider_id
            ),
            worker=None,
            background=None,
            is_default=is_default,
        )

    def _view_row(self, row: LlmModelProfile, *, is_default: bool) -> ModelProfileView:
        main = _slot_from_row(row.main_origin, row.main_model, row.main_provider_id)
        assert main is not None  # DB requires main_model
        return ModelProfileView(
            id=row.id,
            name=row.name,
            kind=row.kind if row.kind in ("user", "implicit") else "user",  # type: ignore[arg-type]
            main=main,
            worker=_slot_from_row(
                row.worker_origin, row.worker_model, row.worker_provider_id
            ),
            background=_slot_from_row(
                row.background_origin, row.background_model, row.background_provider_id
            ),
            is_default=is_default,
        )

    def _visible_system_ids(self) -> list[str]:
        return [pid for pid in SYSTEM_PRESETS if _system_preset_available(pid)]

    def _mark_default(
        self, views: list[ModelProfileView], default_id: str | None
    ) -> list[ModelProfileView]:
        known = {v.id for v in views}
        effective = default_id if default_id in known else None
        if effective is None:
            # No account default (or dangling pin) → 5.2 preset when listed.
            if SYSTEM_PROFILE_DEFAULT in known:
                effective = SYSTEM_PROFILE_DEFAULT
            else:
                effective = next((v.id for v in views if v.kind == "system"), None)
        return [
            ModelProfileView(
                id=v.id,
                name=v.name,
                kind=v.kind,
                main=v.main,
                worker=v.worker,
                background=v.background,
                is_default=(v.id == effective),
            )
            for v in views
        ]

    async def list_profiles(self, user_id: str) -> list[ModelProfileView]:
        default_id = await self._default_id(user_id)
        views = [
            self._view_system(pid, is_default=False)
            for pid in self._visible_system_ids()
        ]
        for row in await self._repo.list_for_user(user_id, include_implicit=False):
            views.append(self._view_row(row, is_default=False))
        return self._mark_default(views, default_id)

    async def get_profile(self, user_id: str, profile_id: str) -> ModelProfileView:
        if is_system_profile_id(profile_id):
            if not _system_preset_available(profile_id):
                raise NotFoundError("模型组合不存在")
            for view in await self.list_profiles(user_id):
                if view.id == profile_id:
                    return view
            raise NotFoundError("模型组合不存在")
        default_id = await self._default_id(user_id)
        row = await self._repo.get(profile_id, user_id=user_id)
        if row is None:
            raise NotFoundError("模型组合不存在")
        return self._view_row(row, is_default=(row.id == default_id))

    async def _validate_slot(
        self, user_id: str, slot: ProfileSlot, *, label: str
    ) -> None:
        if not (slot.model or "").strip():
            raise ValidationError(f"{label} 模型不能为空")
        if slot.origin == "platform":
            if slot.provider_id:
                raise ValidationError(f"{label} 平台模型不能指定服务商")
            if not platform_billing_selectable():
                raise ValidationError("当前部署不可用平台模型")
            from agentcore.llm.catalog import _platform_model_ids

            if slot.model.strip() not in _platform_model_ids():
                raise ValidationError(f"{label} 所选模型不在平台目录中")
            return
        if not slot.provider_id:
            raise ValidationError(f"{label} 自带 Key 模型须指定服务商")
        row = await self._providers.get(slot.provider_id, user_id=user_id)
        if row is None:
            raise ValidationError(f"{label} 所选服务商不存在")

    async def create_profile(
        self,
        user_id: str,
        *,
        name: str,
        main: ProfileSlot,
        worker: ProfileSlot | None = None,
        background: ProfileSlot | None = None,
        kind: str = "user",
        set_as_default: bool = False,
    ) -> ModelProfileView:
        name_s = (name or "").strip()
        if not name_s:
            raise ValidationError("组合名称不能为空")
        await self._validate_slot(user_id, main, label="main")
        if worker is not None:
            await self._validate_slot(user_id, worker, label="worker")
        if background is not None:
            await self._validate_slot(user_id, background, label="background")

        row = await self._repo.create(
            user_id=user_id,
            name=name_s,
            kind=kind,
            main_origin=main.origin,
            main_provider_id=main.provider_id if main.origin == "byok" else None,
            main_model=main.model.strip(),
            worker_origin=worker.origin if worker else None,
            worker_provider_id=(
                worker.provider_id if worker and worker.origin == "byok" else None
            ),
            worker_model=worker.model.strip() if worker else None,
            background_origin=background.origin if background else None,
            background_provider_id=(
                background.provider_id
                if background and background.origin == "byok"
                else None
            ),
            background_model=background.model.strip() if background else None,
        )
        if set_as_default:
            await self._users.set_default_model_profile(user_id, row.id)
        return self._view_row(row, is_default=set_as_default)

    async def update_profile(
        self,
        user_id: str,
        profile_id: str,
        *,
        name: str | None = None,
        main: ProfileSlot | None = None,
        worker: ProfileSlot | None | object = _UNSET,
        background: ProfileSlot | None | object = _UNSET,
        fields_set: set[str],
    ) -> ModelProfileView:
        if is_system_profile_id(profile_id):
            raise ValidationError("系统预置组合不可编辑")
        row = await self._repo.get(profile_id, user_id=user_id)
        if row is None:
            raise NotFoundError("模型组合不存在")
        if row.kind == "implicit":
            raise ValidationError("隐式组合不可编辑，请新建用户组合")

        kwargs: dict = {}
        if "name" in fields_set and name is not None:
            name_s = name.strip()
            if not name_s:
                raise ValidationError("组合名称不能为空")
            kwargs["name"] = name_s
        if "main" in fields_set:
            if main is None:
                raise ValidationError("main 不能为空")
            await self._validate_slot(user_id, main, label="main")
            kwargs["main_origin"] = main.origin
            kwargs["main_provider_id"] = (
                main.provider_id if main.origin == "byok" else None
            )
            kwargs["main_model"] = main.model.strip()
        if "worker" in fields_set:
            if worker is None:
                kwargs["worker_origin"] = None
                kwargs["worker_provider_id"] = None
                kwargs["worker_model"] = None
            else:
                assert isinstance(worker, ProfileSlot)
                await self._validate_slot(user_id, worker, label="worker")
                kwargs["worker_origin"] = worker.origin
                kwargs["worker_provider_id"] = (
                    worker.provider_id if worker.origin == "byok" else None
                )
                kwargs["worker_model"] = worker.model.strip()
        if "background" in fields_set:
            if background is None:
                kwargs["background_origin"] = None
                kwargs["background_provider_id"] = None
                kwargs["background_model"] = None
            else:
                assert isinstance(background, ProfileSlot)
                await self._validate_slot(user_id, background, label="background")
                kwargs["background_origin"] = background.origin
                kwargs["background_provider_id"] = (
                    background.provider_id if background.origin == "byok" else None
                )
                kwargs["background_model"] = background.model.strip()

        updated = await self._repo.update(profile_id, user_id=user_id, **kwargs)
        assert updated is not None
        default_id = await self._default_id(user_id)
        return self._view_row(updated, is_default=(updated.id == default_id))

    async def delete_profile(self, user_id: str, profile_id: str) -> None:
        if is_system_profile_id(profile_id):
            raise ValidationError("系统预置组合不可删除")
        default_id = await self._default_id(user_id)
        if default_id == profile_id:
            raise ValidationError("不能删除账号默认组合，请先切换默认")
        row = await self._repo.get(profile_id, user_id=user_id)
        if row is None:
            raise NotFoundError("模型组合不存在")
        # Conversations pointing here fall back to account default (NULL the pin).
        from agentcore.db.repositories import ConversationRepository

        await ConversationRepository(self._session).clear_model_profile_refs(
            user_id, profile_id
        )
        deleted = await self._repo.delete(profile_id, user_id=user_id)
        if not deleted:
            raise NotFoundError("模型组合不存在")

    async def set_default(self, user_id: str, profile_id: str) -> ModelProfileView:
        if is_system_profile_id(profile_id):
            if not _system_preset_available(profile_id):
                raise ValidationError("所选系统预置当前不可用")
            await self._users.set_default_model_profile(user_id, profile_id)
            return self._view_system(profile_id, is_default=True)
        row = await self._repo.get(profile_id, user_id=user_id)
        if row is None:
            raise NotFoundError("模型组合不存在")
        if row.kind == "implicit":
            raise ValidationError("不能将隐式组合设为账号默认")
        await self._users.set_default_model_profile(user_id, profile_id)
        return self._view_row(row, is_default=True)

    async def ensure_profile_usable(self, user_id: str, profile_id: str) -> None:
        """Raise if ``profile_id`` is not a usable system preset and not owned by the user."""
        if is_system_profile_id(profile_id):
            if not _system_preset_available(profile_id):
                raise ValidationError("所选模型组合当前不可用")
            return
        row = await self._repo.get(profile_id, user_id=user_id)
        if row is None:
            raise ValidationError("所选模型组合不存在或不属于你")

    async def expand(
        self,
        user_id: str,
        profile_id: str | None,
    ) -> ExpandedProfile:
        """Expand a profile id (or account default / 5.2 preset) into live selections."""
        effective = profile_id or await self._default_id(user_id) or SYSTEM_PROFILE_DEFAULT

        if is_system_profile_id(effective):
            if (
                not _system_preset_available(effective)
                and effective != SYSTEM_PROFILE_DEFAULT
            ):
                return await self.expand(user_id, SYSTEM_PROFILE_DEFAULT)
            model_id = SYSTEM_PRESETS[effective]
            name = _system_preset_display_name(model_id)
            main = resolve_system_preset_main(effective)
            if main.origin == "platform" and not platform_billing_selectable():
                main = await _provider_first_fallback(self._session, user_id)
            return ExpandedProfile(
                profile_id=effective,
                name=name,
                kind="system",
                main=main,
                worker=None,
                background=None,
            )

        row = await self._repo.get(effective, user_id=user_id)
        if row is None:
            # Dangling default / conversation pin / retired virtual id → 5.2 preset.
            return await self.expand(user_id, SYSTEM_PROFILE_DEFAULT)

        main_slot = _slot_from_row(row.main_origin, row.main_model, row.main_provider_id)
        assert main_slot is not None
        main = await _live_selection(self._session, user_id, main_slot)

        worker_slot = _slot_from_row(
            row.worker_origin, row.worker_model, row.worker_provider_id
        )
        worker = (
            await _live_selection(self._session, user_id, worker_slot)
            if worker_slot
            else None
        )

        bg_slot = _slot_from_row(
            row.background_origin, row.background_model, row.background_provider_id
        )
        background = (
            await _live_selection(self._session, user_id, bg_slot) if bg_slot else None
        )

        return ExpandedProfile(
            profile_id=row.id,
            name=row.name,
            kind="implicit" if row.kind == "implicit" else "user",
            main=main,
            worker=worker,
            background=background,
        )

    async def expand_for_conversation(
        self, user_id: str, conv
    ) -> ExpandedProfile:
        profile_id = getattr(conv, "model_profile_id", None) or None
        return await self.expand(user_id, profile_id)
