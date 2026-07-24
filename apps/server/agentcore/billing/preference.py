"""Deployment-level billing helpers (platform availability, free tier)."""

from __future__ import annotations

from agentcore.config import settings
from agentcore.config.platform import parse_platform_model_credentials


def is_platform_available() -> bool:
    """Whether the operator configured a usable platform upstream key.

    True when the shared ``platform_api_key`` is set OR any per-model override in
    ``platform_model_credentials`` carries its own key — either is enough to serve at
    least one platform model (per-model credential resolution happens at the call site).
    """
    if settings.platform_api_key.strip():
        return True
    overrides = parse_platform_model_credentials(settings.platform_model_credentials)
    return any(entry.get("api_key") for entry in overrides.values())


def platform_model_allowlist() -> list[str]:
    """Explicit platform model catalog (运营配置, 成本配额与计费 §〇·六 F3).

    Parses the comma-separated ``PLATFORM_MODELS`` env into an ordered, de-duped id
    list. Empty ⇒ ``[]`` and the catalog falls back to ``platform_model`` (+ background
    model) — keeping byok / free-tier deployments unchanged (asset dormancy).
    """
    raw = settings.platform_models or ""
    seen: set[str] = set()
    ordered: list[str] = []
    for part in raw.split(","):
        mid = part.strip()
        if mid and mid not in seen:
            seen.add(mid)
            ordered.append(mid)
    return ordered


def is_free_tier_enabled() -> bool:
    """Deployment switch for keyless → platform-paid free tier fallback."""
    return bool(settings.platform_free_tier_enabled)


def is_free_tier_active(*, has_user_key: bool) -> bool:
    """Whether this user currently rides the free tier (signal for llm-key status).

    True iff: no BYOK key ∧ free tier switch on ∧ platform credentials available.
    """
    return (not has_user_key) and is_free_tier_enabled() and is_platform_available()


def platform_billing_selectable() -> bool:
    """Whether platform-billed model rows are selectable at all (代付总闸).

    Platform deployments always are; BYOK deployments only when the free tier is
    on. A BYOK deployment with the free tier off means the operator does not
    subsidize any calls — platform rows are then withheld from the catalog, a
    stored platform override silently falls back to the account default, and the
    billing gate refuses keyless platform-origin turns with 402 (guide to BYOK).
    Credential availability is a separate check (503).
    """
    return settings.billing_mode == "platform" or is_free_tier_enabled()
