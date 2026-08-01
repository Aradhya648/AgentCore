"""Shared LLM billing preflight for user-facing and background call sites.

Chat turns, file assist, and the inference proxy all refuse or admit an LLM call
with the same per-origin billing decision: ``model_origin=byok`` requires the
user's own key (no quota check); ``model_origin=platform`` enforces quota then
runs on the global key.

Background product chrome (title / memory / compaction / followups) resolves
platform-first via ``resolve_and_gate_background``: platform spend always passes
``enforce_quota`` (no BYOK freeload); quota exhaustion returns ``None`` so
best-effort callers degrade instead of 429-ing the user turn.

Auth-rejected platform keys fall back **once** to user BYOK through
``run_background_llm`` — the sole chrome entry that may retry after
``LLMAuthError``. Call sites must not invent their own try/except BYOK glue or
process-local auth circuit breakers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.preference import platform_catalog_visible
from agentcore.conversation.quota import QuotaLimits, enforce_quota
from agentcore.core.errors import (
    BYOKKeyMissingError,
    LLMAuthError,
    PlatformBillingUnavailableError,
    QuotaExceededError,
)
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import CostEventRepository, UserRepository
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.resolve import (
    ModelConfig,
    ModelOrigin,
    ModelPurpose,
    resolve_background_user_fallback,
    resolve_model_config,
    resolve_user_llm_credentials,
)

logger = get_logger(__name__)

_PLATFORM_UNAVAILABLE_MESSAGE = (
    "平台额度暂不可用（运营方未配置平台 Key，或当前部署未开放平台代付）。"
    "请在设置中切换为自带 API Key，或联系管理员。"
)


@dataclass(frozen=True)
class BackgroundLlmResult[T]:
    """Successful background chrome LLM call: payload + credentials that worked."""

    value: T
    credentials: LLMCredentials


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
    ``QuotaExceededError`` (429), or ``PlatformBillingUnavailableError`` (503)
    when the call must be refused.

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

    if not platform_catalog_visible():
        raise PlatformBillingUnavailableError(_PLATFORM_UNAVAILABLE_MESSAGE)

    await enforce_quota(
        cost_repo,
        user.user_id,
        limits=QuotaLimits.for_user(user),
    )
    return None


def _creds_from_cfg(cfg: ModelConfig) -> LLMCredentials:
    return LLMCredentials(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        default_model=cfg.model,
        source="platform" if cfg.source == "platform" else "user",
        provider_id=cfg.provider_id,
    )


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

    Prefer ``run_background_llm`` at call sites that actually invoke the model: it
    adds the single platform-``LLMAuthError`` → user BYOK retry.
    """
    cfg = await resolve_model_config(session, user_id, purpose)
    if cfg is None:
        return None

    # Dormant / credentials gated off: same as main chat — BYOK or skip.
    if cfg.source == "platform" and not platform_catalog_visible():
        return await resolve_and_gate_background_user_fallback(
            session, user_id, purpose=purpose
        )

    creds = _creds_from_cfg(cfg)
    if cfg.source != "platform":
        return creds

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        return None

    try:
        await enforce_quota(
            CostEventRepository(session),
            user_id,
            limits=QuotaLimits.for_user(user),
        )
    except QuotaExceededError as e:
        logger.info(
            "billing.background_quota_skip",
            user_id=user_id,
            purpose=purpose,
            error=str(e),
        )
        return None
    return creds


async def resolve_and_gate_background_user_fallback(
    session: AsyncSession,
    user_id: str,
    *,
    purpose: ModelPurpose = "title",
) -> LLMCredentials | None:
    """Resolve user BYOK for background chrome after platform is unavailable / auth-rejected.

    ``source=user`` — no platform quota. Returns ``None`` when the account has no
    usable BYOK key (including combo slots that only point at platform).
    """
    cfg = await resolve_background_user_fallback(session, user_id, purpose)
    if cfg is None:
        return None
    return _creds_from_cfg(cfg)


async def run_background_llm[T](
    user_id: str,
    *,
    purpose: ModelPurpose = "title",
    runner: Callable[[LLMCredentials], Awaitable[T]],
) -> BackgroundLlmResult[T] | None:
    """Platform-first background LLM with one BYOK retry on platform ``LLMAuthError``.

    Flow:
    1. ``resolve_and_gate_background`` (platform-first + quota when platform).
    2. Run ``runner(credentials)``.
    3. On ``LLMAuthError`` **and** ``credentials.source == "platform"``: resolve
       user BYOK once via ``resolve_and_gate_background_user_fallback`` and re-run.
    4. Missing credentials on either side, or BYOK also auth-fails → ``None``.
    5. Any other runner exception propagates unchanged.

    No process-local auth circuit breaker — each call re-resolves. Call sites must
    re-raise ``LLMAuthError`` from their generators so this entry can see it.
    """
    async with async_session_factory() as session:
        primary = await resolve_and_gate_background(session, user_id, purpose=purpose)
    if primary is None:
        return None

    try:
        value = await runner(primary)
        return BackgroundLlmResult(value=value, credentials=primary)
    except LLMAuthError:
        if primary.source != "platform":
            # Already on user BYOK — do not bounce back to platform.
            return None

    logger.info(
        "billing.background_platform_auth_fallback",
        user_id=user_id,
        purpose=purpose,
    )
    async with async_session_factory() as session:
        fallback = await resolve_and_gate_background_user_fallback(
            session, user_id, purpose=purpose
        )
    if fallback is None:
        return None

    try:
        value = await runner(fallback)
        return BackgroundLlmResult(value=value, credentials=fallback)
    except LLMAuthError:
        return None
