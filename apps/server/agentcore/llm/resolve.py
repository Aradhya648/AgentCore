"""Unified model + credential resolution for every LLM call site.

BYOK is a **list of providers** (``user_llm_providers``). Account / conversation
select a **model combination profile** (``llm_model_profiles`` / system presets);
expand yields main / worker / background slots (empty = follow_main). This module
is the single choke point that turns「which user / which conversation / which
purpose」into「which upstream endpoint + which model + which price card」.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from agentcore.db.models import UserLlmProvider

from agentcore.config import settings
from agentcore.config.platform import parse_platform_model_credentials
from agentcore.core.logging import get_logger
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.profiles import PLATFORM_MODEL_FLASH

logger = get_logger(__name__)

ProviderPurpose = Literal["user_facing", "platform_internal"]
ModelPurpose = str  # chat | title | memory | compaction | file.rewrite | followups | ...
ModelOrigin = Literal["byok", "platform"]

_BACKGROUND_PURPOSES = frozenset({"title", "memory", "compaction", "followups"})

__all__ = [
    "ModelConfig",
    "ModelOrigin",
    "ModelSelection",
    "ProviderPurpose",
    "platform_llm_credentials",
    "resolve_account_default_model",
    "resolve_account_worker_selection",
    "resolve_conversation_model_selection",
    "resolve_credentials",
    "resolve_model_config",
    "resolve_provider_credentials",
    "resolve_turn_model",
    "resolve_user_chat_model",
    "resolve_user_llm_credentials",
    "list_user_providers",
    "user_has_provider",
]


@dataclass(frozen=True)
class ModelSelection:
    model: str
    origin: ModelOrigin
    # The BYOK provider this selection runs on (None for platform / keyless).
    provider_id: str | None = None


@dataclass(frozen=True)
class ModelConfig:
    model: str
    base_url: str
    api_key: str
    source: Literal["platform", "byok"]
    purpose: str
    price_cache_hit: str | None = None
    price_cache_miss: str | None = None
    price_output: str | None = None
    background_model: str | None = None
    provider_id: str | None = None


def _encryptor():
    from agentcore.security.keys import KeyEncryptor

    if not settings.encryption_key:
        return None
    try:
        return KeyEncryptor(settings.encryption_key)
    except ValueError:
        # Malformed master key must not 500 chat / catalog paths — degrade like
        # a missing key (provider_service raises KeyStorageUnavailableError on write).
        logger.error("byok.key_malformed")
        return None


def _model_for_purpose(
    purpose: str,
    *,
    chat_model: str,
    user_background_model: str | None = None,
) -> str:
    """Resolve model name for ``purpose``; background prefers background_model."""
    if purpose not in _BACKGROUND_PURPOSES:
        return chat_model
    if user_background_model and user_background_model.strip():
        return user_background_model.strip()
    platform_bg = (settings.platform_background_model or "").strip()
    if platform_bg:
        return platform_bg
    return chat_model


def platform_llm_credentials(model: str | None = None) -> LLMCredentials | None:
    """Platform upstream credentials — the single point of per-model resolution.

    ``model`` selects a per-model override (运营中转「一 key 一模型」, 成本配额与计费
    §〇·六 F3): when the id has an entry in ``platform_model_credentials`` its api_key /
    base_url win (each missing field falls back to the shared default), and the returned
    ``default_model`` is that model. A no-arg call is unchanged — the shared
    ``platform_api_key`` / ``platform_base_url`` with ``default_model=platform_model``.
    Returns ``None`` when no usable key resolves for this model (override nor default).
    """
    entry: dict[str, str] = {}
    if model:
        entry = parse_platform_model_credentials(settings.platform_model_credentials).get(
            model, {}
        )
    api_key = (entry.get("api_key") or "").strip() or settings.platform_api_key.strip()
    if not api_key:
        return None
    base_url = (entry.get("base_url") or "").strip() or settings.platform_base_url
    return LLMCredentials(
        api_key=api_key,
        base_url=base_url,
        default_model=model or settings.platform_model,
        source="platform",
    )


# --- provider row helpers ----------------------------------------------------


def _credentials_from_provider(row: UserLlmProvider, api_key: str) -> LLMCredentials:
    return LLMCredentials(
        api_key=api_key,
        base_url=row.base_url or settings.platform_base_url,
        default_model=(row.default_model or "").strip() or PLATFORM_MODEL_FLASH,
        source="user",
        price_cache_hit=getattr(row, "price_cache_hit", None),
        price_cache_miss=getattr(row, "price_cache_miss", None),
        price_output=getattr(row, "price_output", None),
        provider_id=row.id,
    )


def _decrypt_provider(row: UserLlmProvider, user_id: str) -> LLMCredentials | None:
    """Decrypt a provider row's key into ``LLMCredentials`` (None on any failure)."""
    if not row.api_key_enc:
        return None
    enc = _encryptor()
    if enc is None:
        return None
    try:
        api_key = enc.decrypt(row.api_key_enc).decode()
    except Exception as e:  # noqa: BLE001 — corrupt cipher / rotated master key degrades to None
        logger.warning(
            "byok.decrypt_failed", user_id=user_id, provider_id=row.id, error=str(e)
        )
        return None
    return _credentials_from_provider(row, api_key)


async def _load_provider(
    session: AsyncSession, user_id: str, provider_id: str | None
) -> UserLlmProvider | None:
    """Owner-scoped provider fetch by id (None for a missing / non-owned / dangling id)."""
    if not provider_id:
        return None
    from agentcore.db.repositories import UserLlmProviderRepository

    return await UserLlmProviderRepository(session).get(provider_id, user_id=user_id)


async def _default_chat_provider_row(
    session: AsyncSession, user_id: str, *, user=None
) -> UserLlmProvider | None:
    """The account's default BYOK provider row for chat (profile main → first provider).

    Used as a low-level fallback when expanding slots / decrypting without a full
    profile walk. Prefer ``resolve_account_default_model`` for turn selection.
    """
    from agentcore.db.repositories import UserLlmProviderRepository, UserRepository
    from agentcore.llm.model_profiles import (
        SYSTEM_PRESETS,
        is_system_profile_id,
    )

    repo = UserLlmProviderRepository(session)
    if user is None:
        user = await UserRepository(session).get_by_id(user_id)
    profile_id = (
        getattr(user, "default_model_profile_id", None) if user is not None else None
    )
    if profile_id and not is_system_profile_id(profile_id):
        from agentcore.db.repositories import LlmModelProfileRepository

        row_prof = await LlmModelProfileRepository(session).get(
            profile_id, user_id=user_id
        )
        if row_prof is not None and row_prof.main_provider_id:
            row = await repo.get(row_prof.main_provider_id, user_id=user_id)
            if row is not None:
                return row
    elif profile_id in SYSTEM_PRESETS:
        # System presets are platform-origin; no BYOK default row.
        return await repo.first_for_user(user_id)
    return await repo.first_for_user(user_id)


async def _account_default(
    session: AsyncSession, user_id: str
) -> tuple[UserLlmProvider | None, str, ModelOrigin]:
    """(provider_row, model, origin) for the account default chat selection via profile."""
    selection = await resolve_account_default_model(session, user_id)
    row = None
    if selection.origin == "byok" and selection.provider_id:
        row = await _load_provider(session, user_id, selection.provider_id)
    return row, selection.model, selection.origin


async def user_has_provider(session: AsyncSession, user_id: str) -> bool:
    """Whether the user has at least one configured BYOK provider."""
    from agentcore.db.repositories import UserLlmProviderRepository

    return await UserLlmProviderRepository(session).count_for_user(user_id) > 0


async def list_user_providers(session: AsyncSession, user_id: str) -> list[UserLlmProvider]:
    """All of a user's BYOK provider rows (the catalog reads these to discover models).

    Lives on the resolve bridge (the single llm↔db seam) so the catalog stays a pure
    llm-layer module.
    """
    from agentcore.db.repositories import UserLlmProviderRepository

    return list(await UserLlmProviderRepository(session).list_for_user(user_id))


async def resolve_provider_credentials(
    session: AsyncSession, user_id: str, provider_id: str
) -> LLMCredentials | None:
    """Decrypt a specific provider's credentials (owner-scoped). None if missing/undecryptable."""
    row = await _load_provider(session, user_id, provider_id)
    if row is None:
        return None
    return _decrypt_provider(row, user_id)


async def resolve_user_llm_credentials(
    session: AsyncSession, user_id: str, *, provider_id: str | None = None
) -> LLMCredentials | None:
    """BYOK credentials for a ``provider_id``, or the account's default chat provider.

    Kept as the general「the user's BYOK credentials」entry point: callers that pin a
    provider pass ``provider_id``; callers that just want the account default omit it.
    """
    if provider_id:
        return await resolve_provider_credentials(session, user_id, provider_id)
    row = await _default_chat_provider_row(session, user_id)
    if row is None:
        return None
    return _decrypt_provider(row, user_id)


async def resolve_account_default_model(
    session: AsyncSession, user_id: str
) -> ModelSelection:
    """Account default main slot (default profile / system 5.2 preset)."""
    from agentcore.llm.model_profiles import LlmModelProfileService

    expanded = await LlmModelProfileService(session).expand(user_id, None)
    return expanded.main


async def resolve_conversation_model_selection(
    session: AsyncSession,
    conv,
    user_id: str,
) -> ModelSelection:
    """Resolve main model + origin + provider for a user-facing turn (profile expand).

    ``conversations.model_profile_id`` when set; else account ``default_model_profile_id``;
    else system 5.2 preset. Live expand — dangling provider pins fall back silently.
    """
    from agentcore.llm.model_profiles import LlmModelProfileService

    expanded = await LlmModelProfileService(session).expand_for_conversation(
        user_id, conv
    )
    return expanded.main


async def resolve_account_worker_selection(
    session: AsyncSession,
    user_id: str,
    *,
    conv=None,
) -> ModelSelection | None:
    """Worker slot from the effective profile, or None when follow_main.

    When ``conv`` is given, uses that conversation's profile pin (else account default).
    """
    from agentcore.llm.model_profiles import LlmModelProfileService

    svc = LlmModelProfileService(session)
    if conv is not None:
        expanded = await svc.expand_for_conversation(user_id, conv)
    else:
        expanded = await svc.expand(user_id, None)
    return expanded.worker


async def _resolve_background(
    session: AsyncSession, user_id: str
) -> tuple[LLMCredentials, str] | None:
    """Account default profile's background slot → ``(creds, model)``, or None (follow)."""
    from agentcore.llm.model_profiles import LlmModelProfileService

    expanded = await LlmModelProfileService(session).expand(user_id, None)
    bg = expanded.background
    if bg is None:
        return None
    if bg.origin == "platform":
        creds = platform_llm_credentials(model=bg.model)
        if creds is None:
            return None
        return creds, bg.model
    if not bg.provider_id:
        return None
    row = await _load_provider(session, user_id, bg.provider_id)
    if row is None:
        return None
    creds = _decrypt_provider(row, user_id)
    if creds is None:
        return None
    return creds, bg.model


def _model_config_from_creds(
    creds: LLMCredentials, model: str, purpose: str
) -> ModelConfig:
    return ModelConfig(
        model=model,
        base_url=creds.base_url,
        api_key=creds.api_key,
        source="byok" if creds.source != "platform" else "platform",
        purpose=purpose,
        price_cache_hit=creds.price_cache_hit,
        price_cache_miss=creds.price_cache_miss,
        price_output=creds.price_output,
        provider_id=creds.provider_id,
    )


async def resolve_model_config(
    session: AsyncSession,
    user_id: str,
    purpose: ModelPurpose = "chat",
) -> ModelConfig | None:
    """Resolve full upstream config for one LLM purpose.

    SELECTION / ADVISORY ONLY — never an authorization path (01 F10). For a keyless
    user this deliberately FALLS BACK to the platform model so token advisory / turn-
    profile selection still resolves a NAME; the billing gate
    (``preflight_llm_credentials`` / ``resolve_and_gate_background``) is the
    authorization choke point.

    Background purposes (title/memory/compaction/followups) are **platform-first**
    product chrome (industry-aligned: Cursor-style). BYOK is only a fallback when
    platform credentials are unavailable. Chat purpose stays user-key-first unless the
    account default is an explicit platform pointer.
    """
    is_background = purpose in _BACKGROUND_PURPOSES

    if is_background:
        # Platform-first: product shell (titles, memory, …) does not follow the
        # user's chat BYOK key. Model 降档 via platform_background_model.
        platform_model = _model_for_purpose(purpose, chat_model=settings.platform_model)
        platform = platform_llm_credentials(model=platform_model)
        if platform is not None:
            return ModelConfig(
                model=platform_model,
                base_url=platform.base_url,
                api_key=platform.api_key,
                source="platform",
                purpose=purpose,
            )
        bg = await _resolve_background(session, user_id)
        if bg is not None:
            creds, model = bg
            return _model_config_from_creds(creds, model, purpose)
        row, chat_model, _origin = await _account_default(session, user_id)
        if row is not None:
            creds = _decrypt_provider(row, user_id)
            if creds is not None:
                model = _model_for_purpose(
                    purpose, chat_model=chat_model, user_background_model=None
                )
                return _model_config_from_creds(creds, model, purpose)
        return None

    row, chat_model, origin = await _account_default(session, user_id)
    if origin == "byok" and row is not None:
        creds = _decrypt_provider(row, user_id)
        if creds is not None:
            return _model_config_from_creds(creds, chat_model, purpose)

    platform_model = (
        chat_model
        if origin == "platform"
        else _model_for_purpose(purpose, chat_model=settings.platform_model)
    )
    platform = platform_llm_credentials(model=platform_model)
    if platform is not None:
        return ModelConfig(
            model=platform_model,
            base_url=platform.base_url,
            api_key=platform.api_key,
            source="platform",
            purpose=purpose,
        )
    return None


async def resolve_credentials(
    session: AsyncSession,
    user_id: str,
    purpose: ProviderPurpose = "user_facing",
) -> LLMCredentials | None:
    """Legacy credential carrier for factory / route preflight."""
    scenario = "chat" if purpose == "user_facing" else "title"
    cfg = await resolve_model_config(session, user_id, scenario)
    if cfg is None:
        return None
    return LLMCredentials(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        default_model=cfg.model,
        source="platform" if cfg.source == "platform" else "user",
        price_cache_hit=cfg.price_cache_hit,
        price_cache_miss=cfg.price_cache_miss,
        price_output=cfg.price_output,
        provider_id=cfg.provider_id,
    )


def resolve_turn_model(
    credentials: LLMCredentials | None,
    *,
    conversation_model: str | None = None,
) -> str:
    """Resolve the model for a user-facing turn.

    Priority: explicit ``conversation_model`` (already expanded main from the profile)
    > account ``default_model`` (BYOK creds) > ``platform_model`` > Flash.
    """
    if conversation_model and conversation_model.strip():
        return conversation_model.strip()
    if credentials is not None and credentials.default_model:
        return credentials.default_model
    if settings.platform_model:
        return settings.platform_model
    return PLATFORM_MODEL_FLASH


async def resolve_user_chat_model(session: AsyncSession, user_id: str) -> str:
    """Chat model for a user-facing turn — matches inference proxy upstream resolution."""
    cfg = await resolve_model_config(session, user_id, "chat")
    if cfg is not None:
        return cfg.model
    platform = platform_llm_credentials()
    if platform is not None:
        return settings.platform_model
    return PLATFORM_MODEL_FLASH
