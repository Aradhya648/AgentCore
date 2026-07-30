"""User-facing model catalog (模型目录 · 统一混排 多 BYOK 服务商 + 平台).

Resolves the set of models a user may pick, plus the account's currently-resolved
model, for ``GET /v1/users/me/models`` and the conversation-model PATCH validation.

Each catalog row carries ``origin`` (``byok`` | ``platform``) and, for byok rows, the
``provider_id`` + ``provider_label`` of the exact 服务商 it lives under.
``(id, origin, provider_id)`` is the unique key — the SAME model id may appear under
several providers (and once more as a platform row), because「run model X on provider
A」vs「on provider B」vs「on platform free quota」are genuinely different options.

* **byok** rows — proxied from EACH active provider's endpoint ``GET /models`` when
  configured, cached ~10min per ``(provider_id, base_url)``. Upstream failure degrades
  to that provider's locally-known model (never a 500).
* **platform** rows — the operator platform model set when platform credentials exist.

A keyless user on a deployment with no platform subsidy gets an EMPTY catalog — the UI
shows an empty state that guides to 设置·模型配置 (no greyed-out「add a key」guide rows).

Discovery is the source of WHICH models exist; ``model_metadata`` only ENRICHES the
display fields. Pricing reuses the community chain (:func:`pricing_for_model`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.billing.preference import (
    platform_catalog_visible,
    platform_model_allowlist,
)
from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.model_metadata import model_metadata_for
from agentcore.llm.pricing import (
    CredentialSource,
    has_curated_pricing,
    pricing_for_model,
)
from agentcore.llm.profiles import PLATFORM_MODEL_FLASH
from agentcore.llm.resolve import (
    _decrypt_provider,
    list_user_providers,
    resolve_account_default_model,
)

logger = get_logger(__name__)

ModelOrigin = Literal["byok", "platform"]

# BYOK discovery cache: (provider_id, base_url) -> (monotonic_expiry, model_ids).
# Keyed by provider so each 服务商 discovers independently; base_url in the key busts
# the cache when an endpoint is re-pointed.
_DISCOVERY_TTL_SEC = 600.0
_discovery_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}


@dataclass(frozen=True)
class ModelCatalogCurrent:
    id: str
    origin: ModelOrigin
    provider_id: str | None = None


@dataclass(frozen=True)
class ModelCatalogEntry:
    """One selectable (or grey-out) model row for the catalog UI."""

    id: str
    origin: ModelOrigin
    display_name: str
    vendor: str
    capabilities: list[str] = field(default_factory=list)
    context_length: int | None = None
    price: dict[str, str] | None = None
    available: bool = True
    # BYOK rows: which 服务商 this row runs on (None for platform / guide rows).
    provider_id: str | None = None
    provider_label: str | None = None


@dataclass(frozen=True)
class ModelCatalog:
    current: ModelCatalogCurrent
    byok_configured: bool
    models: list[ModelCatalogEntry]


def _price_card(
    model_id: str,
    *,
    credential_source: CredentialSource,
) -> dict[str, str] | None:
    card = pricing_for_model(model_id, credential_source=credential_source)
    if card is None:
        return None
    return {key: str(value) for key, value in card.items()}


def _entry(
    model_id: str,
    *,
    origin: ModelOrigin,
    available: bool,
    credential_source: CredentialSource,
    provider_id: str | None = None,
    provider_label: str | None = None,
) -> ModelCatalogEntry:
    meta = model_metadata_for(model_id)
    return ModelCatalogEntry(
        id=model_id,
        origin=origin,
        display_name=meta.display_name,
        vendor=meta.vendor,
        capabilities=sorted(meta.capabilities),
        context_length=meta.context_length,
        price=_price_card(model_id, credential_source=credential_source),
        available=available,
        provider_id=provider_id,
        provider_label=provider_label,
    )


def _dedupe(ids: list[str]) -> list[str]:
    """Order-preserving de-dupe (dict.fromkeys), dropping blanks."""
    return list(dict.fromkeys(mid for mid in ids if mid))


async def _discover_provider_models(row, creds: LLMCredentials) -> list[str] | None:
    """Proxy one provider's ``GET /models``; cached ~10min. ``None`` on any failure."""
    cache_key = (row.id, creds.base_url)
    now = time.monotonic()
    cached = _discovery_cache.get(cache_key)
    if cached is not None and cached[0] > now:
        return list(cached[1])

    from agentcore.llm.factory import build_provider

    provider = build_provider(creds)
    try:
        ids = await provider.list_models()
    except Exception as e:  # noqa: BLE001 — discovery is best-effort; degrade on any error
        logger.info(
            "model_catalog.discovery_failed",
            provider_id=row.id,
            base_url=creds.base_url,
            error=str(e),
        )
        return None
    finally:
        await provider.close()

    _discovery_cache[cache_key] = (now + _DISCOVERY_TTL_SEC, list(ids))
    return ids


def _provider_entries(
    row, creds: LLMCredentials, discovered: list[str] | None
) -> list[ModelCatalogEntry]:
    """One provider's byok rows: its default model + discovered ids, tagged with provider."""
    current = (creds.default_model or "").strip() or PLATFORM_MODEL_FLASH
    ids = _dedupe([current, *discovered]) if discovered else _dedupe([current])
    label = (row.label or "").strip() or None
    return [
        _entry(
            mid,
            origin="byok",
            available=True,
            credential_source="user",
            provider_id=row.id,
            provider_label=label,
        )
        for mid in ids
    ]


def _platform_model_ids() -> list[str]:
    """The platform catalog's model ids (成本配额与计费 §〇·六 F3).

    Explicit ``PLATFORM_MODELS`` allowlist when set (the flip's curated set); else the
    single ``platform_model`` (+ background) fallback — byok / free-tier deployments
    keep their one dormant platform row unchanged.
    """
    allowlist = platform_model_allowlist()
    if allowlist:
        return _dedupe(allowlist)
    platform_model = (settings.platform_model or "").strip() or PLATFORM_MODEL_FLASH
    background = (settings.platform_background_model or "").strip()
    return _dedupe([platform_model, background])


def _platform_entry(model_id: str) -> ModelCatalogEntry:
    """One platform-billed catalog row (nominal-price ledger, F4).

    A platform catalog model MUST have a curated price card — a Flash
    ``cost.pricing_fallback`` on a platform-billed row is a 漏配缺陷 (F4), so a
    missing card is logged loudly for ops rather than silently degrading the bill.
    """
    if not has_curated_pricing(model_id):
        logger.warning("platform_catalog.pricing_missing", model=model_id)
    return _entry(model_id, origin="platform", available=True, credential_source="platform")


def _platform_entries() -> list[ModelCatalogEntry]:
    return [_platform_entry(mid) for mid in _platform_model_ids()]


async def resolve_model_catalog(session: AsyncSession, user_id: str) -> ModelCatalog:
    """The user's unified model catalog: current default, BYOK flag, and all rows.

    Every active provider is discovered independently and its models mixed in, tagged
    with that provider's id/label. Platform rows appear only when
    :func:`platform_catalog_visible` (billing selectable ∧ credentials configured).
    """
    platform_rows_on = platform_catalog_visible()
    providers = await list_user_providers(session, user_id)
    byok_configured = len(providers) > 0

    selection = await resolve_account_default_model(session, user_id)
    current = ModelCatalogCurrent(
        id=selection.model, origin=selection.origin, provider_id=selection.provider_id
    )

    if not byok_configured:
        # Keyless: platform catalog when subsidized; otherwise an EMPTY catalog (byok
        # deployment with no platform subsidy) — the UI shows an empty state that guides
        # to 设置·模型配置 rather than greyed-out「add a key to unlock」guide rows.
        models = _platform_entries() if platform_rows_on else []
        return ModelCatalog(current=current, byok_configured=False, models=models)

    models: list[ModelCatalogEntry] = []
    seen: set[tuple[str, str, str | None]] = set()

    def _add(entry: ModelCatalogEntry) -> None:
        key = (entry.id, entry.origin, entry.provider_id)
        if key not in seen:
            models.append(entry)
            seen.add(key)

    for row in providers:
        creds = _decrypt_provider(row, user_id)
        if creds is None:
            # Undecryptable provider (rotated master key / corrupt cipher): still surface
            # its default model row so the settings UI shows the provider, greyed out.
            label = (row.label or "").strip() or None
            _add(
                _entry(
                    (row.default_model or "").strip() or PLATFORM_MODEL_FLASH,
                    origin="byok",
                    available=False,
                    credential_source="user",
                    provider_id=row.id,
                    provider_label=label,
                )
            )
            continue
        discovered = await _discover_provider_models(row, creds)
        for entry in _provider_entries(row, creds, discovered):
            _add(entry)

    if platform_rows_on:
        for entry in _platform_entries():
            _add(entry)

    return ModelCatalog(current=current, byok_configured=True, models=models)


async def validate_model_choice(
    session: AsyncSession,
    user_id: str,
    model: str,
    origin: ModelOrigin,
    provider_id: str | None = None,
) -> bool:
    """Whether ``(model, origin, provider_id)`` is valid + available in the catalog.

    For byok rows the provider must match too (the same id under a different provider
    is a different option). ``provider_id`` is ignored for platform rows (always None).
    """
    target = (model or "").strip()
    if not target or origin not in ("byok", "platform"):
        return False
    want_provider = provider_id if origin == "byok" else None
    catalog = await resolve_model_catalog(session, user_id)
    return any(
        entry.id == target
        and entry.origin == origin
        and entry.provider_id == want_provider
        and entry.available
        for entry in catalog.models
    )


def reset_discovery_cache_for_tests() -> None:
    """Clear the BYOK discovery cache (test isolation)."""
    _discovery_cache.clear()
