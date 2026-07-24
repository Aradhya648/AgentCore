"""Model catalog (模型目录): unified BYOK + platform model list.

Backs 会话级模型切换: the compose UI lists these (each row tagged with origin),
greys out unavailable rows, and PATCHes ``conversations.model`` + ``model_origin``.
All routes are scoped to the authenticated user ("me").
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_db
from agentcore.api.schemas import (
    ModelCatalogCurrent,
    ModelCatalogItem,
    ModelCatalogResponse,
    ModelPriceCard,
)
from agentcore.llm.catalog import ModelCatalog, resolve_model_catalog

router = APIRouter(prefix="/users/me/models", tags=["models"])


def _to_response(catalog: ModelCatalog) -> ModelCatalogResponse:
    return ModelCatalogResponse(
        current=ModelCatalogCurrent(
            id=catalog.current.id,
            origin=catalog.current.origin,
            provider_id=catalog.current.provider_id,
        ),
        byok_configured=catalog.byok_configured,
        models=[
            ModelCatalogItem(
                id=item.id,
                origin=item.origin,
                display_name=item.display_name,
                vendor=item.vendor,
                capabilities=item.capabilities,
                context_length=item.context_length,
                price=ModelPriceCard(**item.price) if item.price else None,
                available=item.available,
                provider_id=item.provider_id,
                provider_label=item.provider_label,
            )
            for item in catalog.models
        ],
    )


@router.get("", response_model=ModelCatalogResponse)
async def list_user_models(
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> ModelCatalogResponse:
    """List the models this user may pick + the account's currently-resolved default."""
    return _to_response(await resolve_model_catalog(session, user.user_id))
