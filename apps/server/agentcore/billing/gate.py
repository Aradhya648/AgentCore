"""Shared LLM billing preflight for user-facing and background call sites.

Chat turns, file assist, and the inference proxy all refuse or admit an LLM call
with the same per-origin billing decision: ``model_origin=byok`` requires the
user's own key (no quota check); ``model_origin=platform`` enforces quota then
runs on the global key.

Background product chrome (title / memory / compaction / followups) resolves
platform-first via ``resolve_and_gate_background``: platform spend always passes
``enforce_quota`` (no BYOK freeload); quota exhaustion returns ``None`` so
best-effort callers degrade instead of 429-ing the user turn.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.preference import is_free_tier_enabled, is_platform_available
from agentcore.config import settings
from agentcore.conversation.quota import QuotaLimits, enforce_quota
from agentcore.core.errors import (
    BYOKKeyMissingError,
    FreeTierExhaustedError,
    PlatformBillingUnavailableError,
    QuotaExceededError,
)
from agentcore.core.logging import get_logger
from agentcore.db.repositories import CostEventRepository, UserRepository
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.resolve import (
    ModelOrigin,
    ModelPurpose,
    resolve_model_config,
    resolve_user_llm_credentials,
    user_has_provider,
)

logger = get_logger(__name__)

_PLATFORM_UNAVAILABLE_MESSAGE = (
    "平台免费额度暂不可用（运营方未配置平台 Key）。请在设置中切换为自带 API Key，或联系管理员。"
)


class _BillingGateUser(Protocol):
    user_id: str


async def preflight_llm_credentials(
    *,
    session: AsyncSession,
    user: _BillingGateUser,
    cost_repo: CostEventRepository,
    byok_missing_message: str,
    model_origin: ModelOrigin,
    provider_id: str | None = None,
) -> LLMCredentials | None:
    """Run the shared billing gate before a user-facing LLM call.

    Returns resolved BYOK credentials, or ``None`` when the turn runs on the
    platform key (quota already enforced). Raises ``BYOKKeyMissingError`` (402),
    ``FreeTierExhaustedError`` / ``QuotaExceededError`` (429), or
    ``PlatformBillingUnavailableError`` (503) when the call must be refused.

    ``provider_id`` pins the exact BYOK 服务商 resolved for this turn (from the
    conversation override or the account default). It is authoritative: the turn runs
    on that provider's key. When it is absent / undecryptable the gate falls back to the
    account default provider, then 402s if the user has no usable provider at all.
    """
    if model_origin == "byok":
        credentials = await resolve_user_llm_credentials(
            session, user.user_id, provider_id=provider_id
        )
        if credentials is None and provider_id is not None:
            # Pinned provider gone / undecryptable → account default (silent fallback).
            credentials = await resolve_user_llm_credentials(session, user.user_id)
        if credentials is None:
            raise BYOKKeyMissingError(byok_missing_message)
        return credentials

    if not is_platform_available():
        raise PlatformBillingUnavailableError(_PLATFORM_UNAVAILABLE_MESSAGE)

    has_key = await user_has_provider(session, user.user_id)
    free_tier_path = (not has_key) and is_free_tier_enabled()
    use_free_tier_defaults = settings.billing_mode == "byok"
    await enforce_quota(
        cost_repo,
        user.user_id,
        limits=QuotaLimits.for_user(user, use_free_tier_defaults=use_free_tier_defaults),
        free_tier=free_tier_path,
    )
    return None


async def resolve_and_gate_background(
    session: AsyncSession,
    user_id: str,
    *,
    purpose: ModelPurpose = "title",
) -> LLMCredentials | None:
    """Resolve background credentials (platform-first) and gate platform spend.

    Returns credentials to pass to ``build_provider``, or ``None`` when the caller
    should skip the LLM (no usable key, or platform quota exhausted). Never raises
    quota errors — background paths are best-effort product chrome.

    When ``source=platform``, ``enforce_quota`` always runs (even if the account
    has a BYOK key) so background cannot freeload past the platform cap.
    """
    cfg = await resolve_model_config(session, user_id, purpose)
    if cfg is None:
        return None

    creds = LLMCredentials(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        default_model=cfg.model,
        source="platform" if cfg.source == "platform" else "user",
        provider_id=cfg.provider_id,
    )
    if cfg.source != "platform":
        return creds

    if not is_platform_available():
        return None

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        return None

    has_key = await user_has_provider(session, user_id)
    free_tier_path = (not has_key) and is_free_tier_enabled()
    use_free_tier_defaults = settings.billing_mode == "byok"
    try:
        await enforce_quota(
            CostEventRepository(session),
            user_id,
            limits=QuotaLimits.for_user(user, use_free_tier_defaults=use_free_tier_defaults),
            free_tier=free_tier_path,
        )
    except (QuotaExceededError, FreeTierExhaustedError) as e:
        logger.info(
            "billing.background_quota_skip",
            user_id=user_id,
            purpose=purpose,
            error=str(e),
        )
        return None
    return creds
