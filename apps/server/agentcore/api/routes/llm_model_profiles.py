"""Model combination profiles CRUD (设置·模型组合).

``/v1/users/me/llm-model-profiles`` — list (system presets + user), create / update /
delete user combinations, set account default. Conversation pins use
``PATCH /conversations/{id}`` with ``model_profile_id``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_db
from agentcore.api.schemas import (
    CreateLlmModelProfileRequest,
    LlmModelProfileListResponse,
    LlmModelProfileView,
    ModelProfileSlot,
    SetDefaultModelProfileRequest,
    StatusResponse,
    UpdateLlmModelProfileRequest,
)
from agentcore.core.logging import get_logger
from agentcore.db.repositories import UserRepository
from agentcore.llm.model_profiles import (
    LlmModelProfileService,
    ModelProfileView,
    ProfileSlot,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/users/me/llm-model-profiles", tags=["llm-model-profiles"])


def get_profile_service(session: AsyncSession = Depends(get_db)) -> LlmModelProfileService:
    return LlmModelProfileService(session)


def _slot_to_api(slot: ProfileSlot | None) -> ModelProfileSlot | None:
    if slot is None:
        return None
    return ModelProfileSlot(
        origin=slot.origin, model=slot.model, provider_id=slot.provider_id
    )


def _to_response(view: ModelProfileView) -> LlmModelProfileView:
    return LlmModelProfileView(
        id=view.id,
        name=view.name,
        kind=view.kind,
        main=_slot_to_api(view.main),  # type: ignore[arg-type]
        worker=_slot_to_api(view.worker),
        background=_slot_to_api(view.background),
        is_default=view.is_default,
    )


def _to_service_slot(slot: ModelProfileSlot) -> ProfileSlot:
    return ProfileSlot(
        origin=slot.origin, model=slot.model, provider_id=slot.provider_id
    )


@router.get("", response_model=LlmModelProfileListResponse)
async def list_model_profiles(
    user: AuthUser,
    service: LlmModelProfileService = Depends(get_profile_service),
    session: AsyncSession = Depends(get_db),
):
    views = await service.list_profiles(user.user_id)
    u = await UserRepository(session).get_by_id(user.user_id)
    default_id = getattr(u, "default_model_profile_id", None) if u else None
    return LlmModelProfileListResponse(
        data=[_to_response(v) for v in views],
        default_model_profile_id=default_id,
    )


@router.post("", response_model=LlmModelProfileView, status_code=201)
async def create_model_profile(
    body: CreateLlmModelProfileRequest,
    user: AuthUser,
    service: LlmModelProfileService = Depends(get_profile_service),
):
    view = await service.create_profile(
        user.user_id,
        name=body.name,
        main=_to_service_slot(body.main),
        worker=_to_service_slot(body.worker) if body.worker else None,
        background=_to_service_slot(body.background) if body.background else None,
        set_as_default=body.set_as_default,
    )
    logger.info(
        "llm_model_profile.created",
        user_id=user.user_id,
        profile_id=view.id,
        name=view.name,
    )
    return _to_response(view)


@router.put("/default", response_model=LlmModelProfileView)
async def set_default_model_profile(
    body: SetDefaultModelProfileRequest,
    user: AuthUser,
    service: LlmModelProfileService = Depends(get_profile_service),
):
    return _to_response(await service.set_default(user.user_id, body.profile_id))


@router.get("/{profile_id}", response_model=LlmModelProfileView)
async def get_model_profile(
    profile_id: str,
    user: AuthUser,
    service: LlmModelProfileService = Depends(get_profile_service),
):
    return _to_response(await service.get_profile(user.user_id, profile_id))


@router.patch("/{profile_id}", response_model=LlmModelProfileView)
async def update_model_profile(
    profile_id: str,
    body: UpdateLlmModelProfileRequest,
    user: AuthUser,
    service: LlmModelProfileService = Depends(get_profile_service),
):
    from agentcore.db.repositories._base import _UNSET

    fields = body.model_fields_set
    worker: ProfileSlot | None | object = _UNSET
    if "worker" in fields:
        worker = _to_service_slot(body.worker) if body.worker is not None else None
    background: ProfileSlot | None | object = _UNSET
    if "background" in fields:
        background = (
            _to_service_slot(body.background) if body.background is not None else None
        )
    return _to_response(
        await service.update_profile(
            user.user_id,
            profile_id,
            name=body.name,
            main=_to_service_slot(body.main) if body.main else None,
            worker=worker,
            background=background,
            fields_set=set(fields),
        )
    )


@router.delete("/{profile_id}", response_model=StatusResponse)
async def delete_model_profile(
    profile_id: str,
    user: AuthUser,
    service: LlmModelProfileService = Depends(get_profile_service),
):
    await service.delete_profile(user.user_id, profile_id)
    return StatusResponse()
