"""Desktop minimum-version hard gate (发布与门禁.md §7.6).

When ``DESKTOP_MIN_VERSION`` is set, requests with ``X-Client-Platform=desktop``
whose ``X-Client-Version`` is strictly below the floor are rejected with HTTP
426 ``CLIENT_TOO_OLD``. This is a **global** desktop floor — not the §7.9
per-flag ``min_client_version`` switch.

Fail-open: empty min / non-desktop platform / missing or ``dev`` client version /
semver compare failure → request proceeds. Exempt probes and
``GET /updates/policy`` so outdated clients can still learn the floor and update.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agentcore.config import settings
from agentcore.core.error_codes import ErrorCode

_PLATFORM_HEADER = "x-client-platform"
_VERSION_HEADER = "x-client-version"

# Exact-path exemptions (no /v1 prefix). Outdated desktops must still reach
# health probes and the update policy so they can self-heal.
_EXEMPT_PATHS = frozenset(
    {
        "/livez",
        "/readyz",
        "/version",
        "/updates/policy",
    }
)


def _semver_parts(version: str) -> tuple[int, int, int]:
    """Parse ``major.minor.patch``; strip prerelease suffix like the desktop client."""
    core = (version.split("-", 1)[0] or version).strip()
    bits = core.split(".")
    parts: list[int] = []
    for bit in bits[:3]:
        try:
            parts.append(int(bit))
        except ValueError as exc:
            raise ValueError(f"non-integer semver segment: {bit!r}") from exc
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def compare_semver(a: str, b: str) -> int:
    """Negative when ``a < b``, 0 when equal, positive when ``a > b``."""
    pa, pb = _semver_parts(a), _semver_parts(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def is_desktop_version_outdated(client_version: str, min_version: str) -> bool:
    """True when desktop build is strictly below the configured floor.

    Raises on unparseable versions so callers can fail-open.
    """
    if not min_version.strip():
        return False
    if not client_version.strip() or client_version.strip() == "dev":
        return False
    return compare_semver(client_version, min_version) < 0


def _too_old_response(*, min_version: str) -> JSONResponse:
    message = f"桌面端版本过旧，请更新后再试（最低版本 {min_version}）"
    return JSONResponse(
        status_code=426,
        content={
            "error": {
                "code": ErrorCode.CLIENT_TOO_OLD,
                "message": message,
                "details": {"min_version": min_version},
            }
        },
    )


class DesktopMinVersionMiddleware(BaseHTTPMiddleware):
    """Reject outdated desktop clients on ``/v1/*`` with HTTP 426."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in _EXEMPT_PATHS or not path.startswith("/v1/"):
            return await call_next(request)

        min_version = (settings.desktop_min_version or "").strip()
        if not min_version:
            return await call_next(request)

        platform = (request.headers.get(_PLATFORM_HEADER) or "").strip()
        if platform != "desktop":
            return await call_next(request)

        client_version = (request.headers.get(_VERSION_HEADER) or "").strip()
        if not client_version or client_version == "dev":
            return await call_next(request)

        try:
            outdated = is_desktop_version_outdated(client_version, min_version)
        except ValueError:
            return await call_next(request)

        if outdated:
            return _too_old_response(min_version=min_version)
        return await call_next(request)
