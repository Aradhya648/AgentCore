"""BYOK LLM provider management (设置·模型配置 · 多服务商列表).

A user's list of OpenAI-compatible providers: list (+ account default pointers +
deployment caps), add, edit, remove, and connectivity-test each; plus set the account
chat / background default pointers. Only AES-256-GCM ciphertext is stored for each key
(see llm/provider_service.py). All routes are scoped to the authenticated user ("me").
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_db
from agentcore.api.schemas import (
    CreateLlmProviderRequest,
    LlmDefaultPointer,
    LlmProvidersResponse,
    LlmProviderView,
    SetLlmDefaultsRequest,
    StatusResponse,
    UpdateLlmProviderRequest,
)
from agentcore.core.logging import get_logger
from agentcore.llm.provider_service import (
    LlmDefaultPointer as ServiceDefaultPointer,
)
from agentcore.llm.provider_service import (
    LlmProviderService,
    LlmProvidersView,
)
from agentcore.llm.provider_service import (
    LlmProviderView as ServiceProviderView,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/users/me/llm-providers", tags=["llm-providers"])


def get_llm_provider_service(session: AsyncSession = Depends(get_db)) -> LlmProviderService:
    return LlmProviderService(session)


def _provider_to_response(view: ServiceProviderView) -> LlmProviderView:
    return LlmProviderView(
        id=view.id,
        label=view.label,
        base_url=view.base_url,
        default_model=view.default_model,
        status=view.status,
        masked_key=view.masked_key,
        supports_tools=view.supports_tools,
        price_cache_hit=view.price_cache_hit,
        price_cache_miss=view.price_cache_miss,
        price_output=view.price_output,
        is_default_chat=view.is_default_chat,
        is_default_background=view.is_default_background,
        message=view.message,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _pointer_to_response(pointer) -> LlmDefaultPointer | None:
    if pointer is None:
        return None
    return LlmDefaultPointer(provider_id=pointer.provider_id, model=pointer.model)


def _collection_to_response(view: LlmProvidersView) -> LlmProvidersResponse:
    return LlmProvidersResponse(
        providers=[_provider_to_response(p) for p in view.providers],
        default_chat=_pointer_to_response(view.default_chat),
        default_background=_pointer_to_response(view.default_background),
        billing_mode=view.billing_mode,
        platform_available=view.platform_available,
        platform_model=view.platform_model,
        free_tier_active=view.free_tier_active,
    )


@router.get("", response_model=LlmProvidersResponse)
async def list_llm_providers(
    user: AuthUser,
    service: LlmProviderService = Depends(get_llm_provider_service),
):
    """The user's BYOK providers + account default pointers + deployment capabilities."""
    return _collection_to_response(await service.list_providers(user.user_id))


@router.post("", response_model=LlmProviderView, status_code=201)
async def create_llm_provider(
    body: CreateLlmProviderRequest,
    user: AuthUser,
    service: LlmProviderService = Depends(get_llm_provider_service),
):
    """Add an OpenAI-compatible provider (key encrypted at rest; status 'unchecked')."""
    view = await service.create_provider(
        user.user_id,
        label=body.label,
        api_key=body.api_key,
        base_url=body.base_url,
        default_model=body.default_model,
        price_cache_hit=body.price_cache_hit,
        price_cache_miss=body.price_cache_miss,
        price_output=body.price_output,
    )
    logger.info(
        "llm_provider.created",
        user_id=user.user_id,
        provider_id=view.id,
        base_url=view.base_url,
        default_model=view.default_model,
    )
    return _provider_to_response(view)


@router.put("/defaults", response_model=LlmProvidersResponse)
async def set_llm_defaults(
    body: SetLlmDefaultsRequest,
    user: AuthUser,
    service: LlmProviderService = Depends(get_llm_provider_service),
):
    """Set the account chat / background default model pointers (each provider+model)."""
    fields = body.model_fields_set
    chat = (
        ServiceDefaultPointer(provider_id=body.chat.provider_id, model=body.chat.model)
        if body.chat is not None
        else None
    )
    background = (
        ServiceDefaultPointer(
            provider_id=body.background.provider_id, model=body.background.model
        )
        if body.background is not None
        else None
    )
    view = await service.set_defaults(
        user.user_id,
        chat=chat,
        background=background,
        set_chat="chat" in fields,
        set_background="background" in fields,
    )
    return _collection_to_response(view)


@router.patch("/{provider_id}", response_model=LlmProviderView)
async def update_llm_provider(
    provider_id: str,
    body: UpdateLlmProviderRequest,
    user: AuthUser,
    service: LlmProviderService = Depends(get_llm_provider_service),
):
    """Update a provider (endpoint / model / label / price; key optional to keep)."""
    view = await service.update_provider(
        user.user_id,
        provider_id,
        label=body.label,
        api_key=body.api_key,
        base_url=body.base_url,
        default_model=body.default_model,
        price_cache_hit=body.price_cache_hit,
        price_cache_miss=body.price_cache_miss,
        price_output=body.price_output,
        fields_set=set(body.model_fields_set),
    )
    return _provider_to_response(view)


@router.delete("/{provider_id}", response_model=StatusResponse)
async def delete_llm_provider(
    provider_id: str,
    user: AuthUser,
    service: LlmProviderService = Depends(get_llm_provider_service),
):
    """Remove a provider (account pointers + conversation overrides fall back cleanly)."""
    await service.delete_provider(user.user_id, provider_id)
    return StatusResponse()


@router.post("/{provider_id}/test", response_model=LlmProviderView)
async def test_llm_provider(
    provider_id: str,
    user: AuthUser,
    service: LlmProviderService = Depends(get_llm_provider_service),
):
    """Probe one provider's endpoint and persist 'active' / 'error' + supports_tools."""
    return _provider_to_response(await service.test_provider(user.user_id, provider_id))
