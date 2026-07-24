"""Shared LLM billing preflight for user-facing call sites.

Chat turns, file assist, and the inference proxy all refuse or admit an LLM call
with the same per-origin billing decision: ``model_origin=byok`` requires the
user's own key (no quota check); ``model_origin=platform`` enforces quota then
runs on the global key.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.preference import is_free_tier_enabled, is_platform_available
from agentcore.config import settings
from agentcore.conversation.quota import QuotaLimits, enforce_quota
from agentcore.core.errors import BYOKKeyMissingError, PlatformBillingUnavailableError
from agentcore.db.repositories import CostEventRepository
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.resolve import (
    ModelOrigin,
    resolve_user_llm_credentials,
    user_has_provider,
)

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
