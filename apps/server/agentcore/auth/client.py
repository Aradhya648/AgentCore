"""Client platform identification for session audience (aud) binding."""

from typing import Literal

from fastapi import Header

ClientPlatform = Literal["desktop", "admin", "mobile"]
TokenAudience = Literal["product", "admin"]

_PRODUCT_PLATFORMS: frozenset[str] = frozenset({"desktop", "mobile"})


def parse_client_platform(
    x_client_platform: str | None = Header(default=None, alias="X-Client-Platform"),
) -> ClientPlatform:
    """Resolve the calling client from ``X-Client-Platform``.

    Defaults to ``desktop`` when absent (legacy tests / curl). Unknown values are
    treated as ``desktop`` so product clients keep working.
    """
    raw = (x_client_platform or "desktop").strip().lower()
    if raw == "admin":
        return "admin"
    if raw == "mobile":
        return "mobile"
    return "desktop"


def platform_to_audience(platform: ClientPlatform) -> TokenAudience:
    """Map a client platform to the JWT ``aud`` claim issued at login."""
    return "admin" if platform == "admin" else "product"


def is_product_platform(platform: ClientPlatform) -> bool:
    return platform in _PRODUCT_PLATFORMS
