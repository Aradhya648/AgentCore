"""Model catalog (模型目录 · 统一混排) response schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class ModelPriceCard(BaseModel):
    """Reused price card — USD per 1M tokens as decimal strings (money is never float)."""

    cache_hit: str | None = None
    cache_miss: str | None = None
    output: str | None = None


class ModelCatalogCurrent(BaseModel):
    id: str = Field(description="The model id the account currently resolves to.")
    origin: Literal["byok", "platform"] = Field(
        description="Credential origin for the account default model."
    )
    provider_id: str | None = Field(
        default=None,
        description="The BYOK provider the default runs on (null for platform / keyless).",
    )


class ModelCatalogItem(BaseModel):
    """One selectable (or greyed-out) model in the user's catalog.

    ``(id, origin, provider_id)`` is the unique key — the same model id may appear under
    several BYOK providers (and once as a platform row), so the picker groups by provider.
    """

    id: str
    origin: Literal["byok", "platform"] = Field(
        description="Credential origin when this model is selected."
    )
    display_name: str
    vendor: str
    capabilities: list[str] = Field(
        default_factory=list,
        description="Enabled capability tags — a subset of vision / tools / reasoning.",
    )
    context_length: int | None = Field(
        default=None, description="Context window in tokens (display hint; null if unknown)."
    )
    price: ModelPriceCard | None = None
    available: bool = Field(
        default=True,
        description=(
            "Whether the user can switch to this (id, origin, provider_id) now. False = "
            "needs a BYOK key or platform unavailable — the UI greys it and guides to 设置."
        ),
    )
    provider_id: str | None = Field(
        default=None,
        description="For byok rows, the provider this model runs on (null for platform).",
    )
    provider_label: str | None = Field(
        default=None, description="Display name of the provider (byok rows only)."
    )


class ModelCatalogResponse(BaseModel):
    """``GET /v1/users/me/models`` — unified model catalog + account default."""

    current: ModelCatalogCurrent
    byok_configured: bool = Field(
        description="Whether the user has at least one BYOK provider configured."
    )
    models: list[ModelCatalogItem]
