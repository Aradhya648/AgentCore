"""Deployment-level billing helpers (platform availability)."""

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
    model).
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


def platform_billing_selectable() -> bool:
    """Whether platform-billed model rows are selectable at all (代付总闸).

    Only ``billing_mode=platform`` opens the gate. BYOK deployments do not subsidize
    calls — platform rows are withheld, a stored platform override falls back to the
    account default, and the billing gate refuses keyless platform-origin turns with
    402 (guide to BYOK). Credential availability is a separate check (see
    :func:`platform_catalog_visible`).
    """
    return settings.billing_mode == "platform"


def platform_catalog_visible() -> bool:
    """Single gate for platform catalog / presets / providers signal / paid paths.

    ``platform_billing_selectable() ∧ is_platform_available()``. When false
    (BYOK deployment, or missing credentials), system presets hide, catalog has no
    platform rows, providers report platform unavailable, and background chrome must
    not spend on the platform key — even if ``PLATFORM_API_KEY`` is still configured.
    """
    return platform_billing_selectable() and is_platform_available()
