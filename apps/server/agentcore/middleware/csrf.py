"""CSRF protection for cookie-authenticated clients (admin console, desktop).

Cross-origin SPAs cannot read an API-scoped cookie, so the token is delivered via the
``X-CSRF-Token`` response header on login/refresh (CORS-exposed) and the client echoes
it in the same header on mutating requests. The token is **stateless**: it is
HMAC-signed and verified against the request's authenticated ``user_id`` (see
:func:`agentcore.security.sign_csrf_token`), so it survives server restarts/reloads and
works across workers with no shared store. Bearer-token clients (mobile) are exempt.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agentcore.api.dependencies import ACCESS_TOKEN_COOKIE
from agentcore.config import settings
from agentcore.core.errors import AuthenticationError
from agentcore.security.csrf import sign_csrf_token, verify_csrf_token
from agentcore.security.tokens import decode_access_token

CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "csrf_token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PREFIXES = (
    "/v1/auth/login",
    "/v1/auth/register",
    "/v1/auth/refresh",
    "/v1/auth/token",
    "/v1/hooks/",
    "/shared/",
)


def issue_csrf_token(
    response: Response, user_id: str, *, persist_session: bool = True
) -> str:
    """Mint a CSRF token for ``user_id`` and attach it to the login/refresh response.

    Returned via the CORS-exposed ``X-CSRF-Token`` header (what the SPA reads) plus a
    non-httpOnly ``csrf_token`` cookie (convenience for same-origin clients).
    """
    token = sign_csrf_token(user_id)
    response.headers[CSRF_HEADER] = token
    cookie_kwargs: dict = {
        "key": CSRF_COOKIE,
        "value": token,
        "httponly": False,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }
    if persist_session:
        cookie_kwargs["max_age"] = settings.jwt_refresh_token_expire_days * 86400
    response.set_cookie(**cookie_kwargs)
    return token


def clear_csrf_token(response: Response, user_id: str | None = None) -> None:
    """Drop the CSRF cookie on logout.

    Stateless tokens have no server state to revoke; the access cookie is the session
    gate, and once it is cleared CSRF is no longer enforced. ``user_id`` is accepted
    for call-site symmetry with :func:`issue_csrf_token` but is unused.
    """
    del user_id
    response.delete_cookie(CSRF_COOKIE, path="/")


def _bearer_present(request: Request) -> bool:
    auth = request.headers.get("authorization") or ""
    return auth.lower().startswith("bearer ")


def _csrf_user_id(request: Request) -> str | None:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token:
        return None
    try:
        return decode_access_token(token)
    except AuthenticationError:
        return None


class CsrfMiddleware(BaseHTTPMiddleware):
    """Require a valid ``X-CSRF-Token`` on cookie-session mutating requests."""

    async def dispatch(self, request: Request, call_next):
        if not settings.csrf_enabled:
            return await call_next(request)
        if request.method in _SAFE_METHODS:
            return await call_next(request)
        if any(request.url.path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)
        # Exempt ONLY a pure bearer client (mobile) — one with no session cookie.
        # A request that carries the access cookie must still pass CSRF even if it
        # also sends an Authorization header: the auth layer prefers the cookie
        # (``access_token or bearer``), so without this clause an attacker could
        # skip CSRF entirely by adding a bogus ``Authorization: Bearer`` header to a
        # cross-site request while still authenticating via the ambient cookie —
        # collapsing CSRF protection onto the CORS allowlist (SEC-003).
        if _bearer_present(request) and not request.cookies.get(ACCESS_TOKEN_COOKIE):
            return await call_next(request)
        user_id = _csrf_user_id(request)
        if user_id is None:
            return await call_next(request)

        header = request.headers.get(CSRF_HEADER) or ""
        if not header or not verify_csrf_token(user_id, header):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "CSRF_FAILED",
                        "message": "CSRF token missing or invalid. Re-login and retry.",
                    }
                },
            )
        return await call_next(request)
