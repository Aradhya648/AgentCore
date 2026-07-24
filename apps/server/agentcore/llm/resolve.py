"""Unified model + credential resolution for every LLM call site.

BYOK is a **list of providers** (``user_llm_providers``): a user may configure many
OpenAI-compatible endpoints at once. The account picks a default chat provider and a
default background provider via pointers on the ``users`` row; a conversation may
override the model per-turn and pin the exact provider (``conversations.model_provider_id``).
This module is the single choke point that turns「which user / which conversation / which
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
    """The account's default chat provider row: pointer → provider, else oldest provider.

    A dangling pointer (provider deleted) silently falls back to the user's sole/first
    provider, matching the「删除服务商静默回落账号默认」contract.
    """
    from agentcore.db.repositories import UserLlmProviderRepository, UserRepository

    repo = UserLlmProviderRepository(session)
    if user is None:
        user = await UserRepository(session).get_by_id(user_id)
    if user is not None and getattr(user, "default_chat_provider_id", None):
        row = await repo.get(user.default_chat_provider_id, user_id=user_id)
        if row is not None:
            return row
    return await repo.first_for_user(user_id)


async def _account_default(
    session: AsyncSession, user_id: str
) -> tuple[UserLlmProvider | None, str, ModelOrigin]:
    """(provider_row, model, origin) for the account default chat selection.

    BYOK when a provider exists (pointer model → provider default_model → Flash). When
    the user has no provider: platform when the operator subsidizes it
    (``platform_billing_selectable``), else origin stays ``byok`` so the billing gate
    refuses keyless turns with 402 (selection stays advisory — the NAME still resolves).
    """
    from agentcore.billing.preference import platform_billing_selectable
    from agentcore.db.repositories import UserRepository

    user = await UserRepository(session).get_by_id(user_id)
    row = await _default_chat_provider_row(session, user_id, user=user)
    if row is not None:
        model = None
        if user is not None and getattr(user, "default_chat_provider_id", None) == row.id:
            model = (user.default_chat_model or "").strip() or None
        model = model or (row.default_model or "").strip() or PLATFORM_MODEL_FLASH
        return row, model, "byok"
    platform_model = (settings.platform_model or "").strip() or PLATFORM_MODEL_FLASH
    origin: ModelOrigin = "platform" if platform_billing_selectable() else "byok"
    return None, platform_model, origin


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
    """Account default when no conversation override applies."""
    row, model, origin = await _account_default(session, user_id)
    return ModelSelection(model=model, origin=origin, provider_id=row.id if row else None)


async def resolve_conversation_model_selection(
    session: AsyncSession,
    conv,
    user_id: str,
) -> ModelSelection:
    """Resolve model + origin + provider for a user-facing turn (override > account default).

    Override rows carry ``(model, model_origin, model_provider_id)``:
    - ``origin=platform`` → platform selection (provider_id None); if the operator
      turned platform billing off, degrade to the account default.
    - ``origin=byok`` with a live ``model_provider_id`` → keep the model on that provider.
    - ``origin=byok`` with ``model_provider_id`` NULL (legacy / pre-multi-provider) →
      keep the model, resolve credentials via the account's sole/default provider.
    - ``origin=byok`` whose pinned provider was deleted, or the account now has no
      provider at all → silent full fallback to the account default (never a hard fail).
    - legacy ``model`` set with ``model_origin`` NULL → byok when the user has any
      provider, else platform.
    """
    from agentcore.billing.preference import platform_billing_selectable

    model = (getattr(conv, "model", None) or "").strip() or None
    if not model:
        return await resolve_account_default_model(session, user_id)

    origin_raw = getattr(conv, "model_origin", None)
    provider_id_raw = getattr(conv, "model_provider_id", None) or None

    origin: ModelOrigin
    if origin_raw in ("byok", "platform"):
        origin = origin_raw  # type: ignore[assignment]
    else:
        origin = "byok" if await user_has_provider(session, user_id) else "platform"

    if origin == "platform":
        if not platform_billing_selectable():
            return await resolve_account_default_model(session, user_id)
        return ModelSelection(model=model, origin="platform", provider_id=None)

    # byok — pin the exact provider when set and live.
    if provider_id_raw:
        row = await _load_provider(session, user_id, provider_id_raw)
        if row is not None:
            return ModelSelection(model=model, origin="byok", provider_id=row.id)
        # Pinned provider deleted → silent full fallback (decision 6).
        return await resolve_account_default_model(session, user_id)

    # Legacy byok override without a pinned provider → keep model on the default provider.
    row = await _default_chat_provider_row(session, user_id)
    if row is not None:
        return ModelSelection(model=model, origin="byok", provider_id=row.id)
    return await resolve_account_default_model(session, user_id)


async def _resolve_background(
    session: AsyncSession, user_id: str
) -> tuple[LLMCredentials, str] | None:
    """The account background pointer's ``(creds, model)``, or None when unset/unresolvable."""
    from agentcore.db.repositories import UserRepository

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not getattr(user, "default_background_provider_id", None):
        return None
    row = await _load_provider(session, user_id, user.default_background_provider_id)
    if row is None:
        return None
    creds = _decrypt_provider(row, user_id)
    if creds is None:
        return None
    model = (
        (user.default_background_model or "").strip()
        or (row.default_model or "").strip()
        or PLATFORM_MODEL_FLASH
    )
    return creds, model


def _model_config_from_creds(
    creds: LLMCredentials, model: str, purpose: str
) -> ModelConfig:
    return ModelConfig(
        model=model,
        base_url=creds.base_url,
        api_key=creds.api_key,
        source="byok",
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
    (``preflight_llm_credentials``) is the single authorization choke point.

    D6: background purposes (title/memory/compaction/followups) prefer the account's
    background provider pointer when set; else follow the chat provider with the
    background *model*降档 (``platform_background_model`` fallback). Keyless users fall
    to the platform key.
    """
    is_background = purpose in _BACKGROUND_PURPOSES

    if is_background:
        bg = await _resolve_background(session, user_id)
        if bg is not None:
            creds, model = bg
            return _model_config_from_creds(creds, model, purpose)

    row, chat_model, _origin = await _account_default(session, user_id)
    if row is not None:
        creds = _decrypt_provider(row, user_id)
        if creds is not None:
            model = (
                _model_for_purpose(purpose, chat_model=chat_model, user_background_model=None)
                if is_background
                else chat_model
            )
            return _model_config_from_creds(creds, model, purpose)

    # Platform fallback: resolve the purpose-downgraded model name first, then its
    # per-model credential (background 降档 may pick a different id than chat).
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

    Priority (会话级模型切换 MVP): ``conversation.model`` (session override) >
    account ``default_model`` (BYOK creds) > ``platform_model`` > ``deepseek-v4-flash``.

    ``conversation_model`` is the session-level override (``conversations.model``),
    already validated against the user's catalog at write time (crud.py PATCH). Only
    the MAIN chat turn threads it in (cloud via ``resolve_turn_profiles``; the sidecar
    path via the inference proxy) — worker / debate fallback is unchanged.
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
