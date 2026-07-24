"""Stateless HMAC-signed CSRF tokens for cookie-session clients."""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from agentcore.config import settings

# Cookie-session clients (admin console, desktop) echo this token in an
# ``X-CSRF-Token`` header on mutating requests. It is STATELESS by design: the
# signature is recomputed from the request's authenticated ``user_id`` at verify
# time, so there is no server-side store. This matches the stateless JWT access
# cookie it rides alongside — a server-stored synchronizer token would be orphaned
# on every restart/reload and across workers, 403-ing an otherwise-valid session.
# The token carries no secret (nonce + expiry + signature); an attacker's
# cross-origin page can neither read it (CORS) nor forge it (no signing key) — which
# is exactly the CSRF guarantee. Wire format: ``v1.<nonce>.<exp>.<sig>``.

_CSRF_TOKEN_VERSION = "v1"
_CSRF_KEY_INFO = b"agentcore.csrf.v1"


def _csrf_signing_key() -> bytes:
    """Derive a dedicated CSRF signing key from the JWT secret (domain separation,
    so one secret never directly signs two distinct token formats)."""
    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"), _CSRF_KEY_INFO, hashlib.sha256
    ).digest()


def _csrf_sign(message: str) -> str:
    digest = hmac.new(_csrf_signing_key(), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def sign_csrf_token(user_id: str, *, ttl_seconds: int | None = None) -> str:
    """Mint a stateless, HMAC-signed CSRF token bound to ``user_id``.

    The lifetime defaults to the refresh-token window; since every login/refresh
    re-issues a token long before then, expiry is never the binding constraint in a
    live session.
    """
    ttl = (
        ttl_seconds
        if ttl_seconds is not None
        else settings.jwt_refresh_token_expire_days * 86400
    )
    nonce = secrets.token_urlsafe(16)
    exp = int(datetime.now(UTC).timestamp()) + ttl
    sig = _csrf_sign(f"{_CSRF_TOKEN_VERSION}.{user_id}.{nonce}.{exp}")
    return f"{_CSRF_TOKEN_VERSION}.{nonce}.{exp}.{sig}"


def verify_csrf_token(user_id: str, token: str) -> bool:
    """Return True iff ``token`` is a valid, unexpired CSRF token for ``user_id``.

    Constant-time signature check, no server state. ``user_id`` comes from the
    verified access-token cookie, which binds the token to that session (another
    user's token recomputes to a different signature and fails).
    """
    parts = token.split(".")
    if len(parts) != 4:
        return False
    version, nonce, exp_raw, sig = parts
    if version != _CSRF_TOKEN_VERSION:
        return False
    try:
        exp = int(exp_raw)
    except ValueError:
        return False
    if exp < int(datetime.now(UTC).timestamp()):
        return False
    expected = _csrf_sign(f"{version}.{user_id}.{nonce}.{exp}")
    return hmac.compare_digest(expected, sig)
