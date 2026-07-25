"""BYOK LLM provider configuration (多服务商列表, llm/provider_service.py) schemas.

A user configures a LIST of OpenAI-compatible providers (each: label + key + endpoint +
default model + optional price card). Account / conversation model selection uses
**model combination profiles** (see ``llm_model_profiles`` schemas) — not bare
per-slot pointers on this response.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from agentcore.config import settings
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH


class _PriceCardFields(BaseModel):
    price_cache_hit: str | None = Field(
        default=None,
        max_length=40,
        description="Optional provider USD per 1M cache-hit tokens (decimal string)",
    )
    price_cache_miss: str | None = Field(
        default=None,
        max_length=40,
        description="Optional provider USD per 1M cache-miss tokens (decimal string)",
    )
    price_output: str | None = Field(
        default=None,
        max_length=40,
        description="Optional provider USD per 1M output tokens (decimal string)",
    )


class CreateLlmProviderRequest(_PriceCardFields):
    """Add one OpenAI-compatible BYOK provider to the account's list."""

    label: str = Field(
        default="",
        max_length=100,
        description="Display name for this provider (e.g. DeepSeek, 火山方舟)",
    )
    api_key: str = Field(
        ...,
        max_length=400,
        description="Plaintext API key (stored AES-256-GCM encrypted; never returned).",
    )
    base_url: str | None = Field(
        default=None,
        max_length=500,
        description="OpenAI-compatible endpoint including version prefix",
        examples=[settings.platform_base_url],
    )
    default_model: str | None = Field(
        default=None,
        max_length=200,
        description="This provider's default model name",
        examples=[DEEPSEEK_V4_FLASH],
    )


class UpdateLlmProviderRequest(_PriceCardFields):
    """Partial update of a provider. Only fields present in the body are applied; an
    omitted ``api_key`` keeps the stored ciphertext (edit endpoint/model without
    re-entering the key)."""

    label: str | None = Field(default=None, max_length=100)
    api_key: str | None = Field(default=None, max_length=400)
    base_url: str | None = Field(default=None, max_length=500)
    default_model: str | None = Field(default=None, max_length=200)


class LlmProviderView(BaseModel):
    """Settings view of one BYOK provider — never the plaintext key."""

    id: str
    label: str
    base_url: str
    default_model: str
    status: str = Field(description="Connectivity result: unchecked | active | error")
    masked_key: str | None = None
    supports_tools: bool | None = None
    price_cache_hit: str | None = None
    price_cache_miss: str | None = None
    price_output: str | None = None
    # Transient message from the connectivity test (POST .../test) only.
    message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LlmProvidersResponse(BaseModel):
    """The full 设置·模型配置 state: provider list + deployment caps.

    Account default combination lives on ``/users/me/llm-model-profiles``
    (``default_model_profile_id``).
    """

    providers: list[LlmProviderView]
    default_model_profile_id: str | None = None
    billing_mode: str = Field(
        default="byok",
        description=(
            "Deployment billing mode (config.billing_mode). In 'platform' a keyless "
            "user runs on platform credit and BYOK is opt-in; in 'byok' a provider is "
            "required unless the free tier is active."
        ),
    )
    platform_available: bool = Field(
        default=False, description="Whether platform models are available on this deployment"
    )
    platform_model: str | None = Field(
        default=None, description="Operator platform model id when platform is available"
    )
    free_tier_active: bool = Field(
        default=False,
        description=(
            "True when this user has no BYOK provider, free tier is enabled, and "
            "platform credentials are available (keyless users can chat on free quota)"
        ),
    )
