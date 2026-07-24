"""JWT access and inference tokens (python-jose)."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from jose import JWTError, jwt

from agentcore.config import settings
from agentcore.core.errors import AuthenticationError

_JWT_ALGORITHM = "HS256"

TokenAudience = Literal["product", "admin"]
AccessTokenClaims = tuple[str, TokenAudience]
MfaPendingClaims = tuple[str, TokenAudience]


def create_access_token(
    user_id: str,
    *,
    audience: TokenAudience,
    family: str | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Mint a short-lived access JWT carrying ``user_id`` as the subject.

    ``family`` (claim ``fam``) binds the access token to its refresh-token family
    so session-management endpoints can mark the current device. Omitted only for
    legacy test helpers; production issuance always passes it.
    """
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.jwt_access_token_expire_minutes))
    claims: dict = {
        "sub": user_id,
        "type": "access",
        "session": audience,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if family is not None:
        claims["fam"] = family
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """Return the subject (user_id) of a valid access token.

    Raises ``AuthenticationError`` for any invalid, tampered, expired, or
    wrong-type token so callers can translate it to a 401 uniformly.
    """
    user_id, _aud = decode_access_token_claims(token)
    return user_id


def decode_access_token_claims(token: str) -> AccessTokenClaims:
    """Return ``(user_id, audience)`` from a valid access token."""
    claims = _decode_access_claims(token)
    return claims["sub"], claims["session"]


def decode_access_token_family(token: str) -> str | None:
    """Return the ``fam`` claim if present; ``None`` for legacy tokens without it.

    Still validates the token (type / signature / expiry) so callers can trust a
    missing fam as "old token", not "invalid token".
    """
    claims = _decode_access_claims(token)
    fam = claims.get("fam")
    return fam if isinstance(fam, str) and fam else None


def _decode_access_claims(token: str) -> dict:
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired token") from exc

    if claims.get("type") != "access":
        raise AuthenticationError("Wrong token type")
    sub = claims.get("sub")
    if not sub:
        raise AuthenticationError("Token missing subject")
    aud = claims.get("session")
    if aud not in ("product", "admin"):
        raise AuthenticationError("Token missing session audience")
    return claims


def create_mfa_pending_token(
    user_id: str,
    *,
    audience: TokenAudience,
    expires_delta: timedelta | None = None,
) -> str:
    """Short-lived token gating the second login factor (password already verified)."""
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=5))
    claims = {
        "sub": user_id,
        "type": "mfa_pending",
        "session": audience,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)


def decode_mfa_pending_token(token: str) -> MfaPendingClaims:
    """Return ``(user_id, audience)`` from a valid MFA-pending token."""
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired MFA session") from exc

    if claims.get("type") != "mfa_pending":
        raise AuthenticationError("Wrong token type")
    sub = claims.get("sub")
    if not sub:
        raise AuthenticationError("Token missing subject")
    aud = claims.get("session")
    if aud not in ("product", "admin"):
        raise AuthenticationError("Token missing session audience")
    return sub, aud


def create_inference_token(user_id: str, *, expires_delta: timedelta | None = None) -> str:
    """Mint a scoped token authorizing a local sidecar's LLM calls through the cloud
    inference proxy (双模式工作区 §一.1 / Slice 4a).

    The desktop authenticates via httpOnly cookies, so the renderer can never hand
    the sidecar a usable bearer; instead it exchanges its cookie for THIS token and
    passes it to the on-machine engine, which sends it as ``Authorization: Bearer``
    to ``/v1/inference``. A distinct ``type`` ("inference", not "access") means it
    can ONLY authorize the inference proxy — :func:`decode_inference_token` refuses
    an access token and :func:`decode_access_token` refuses this one, so the two kinds
    can never be confused (a leaked inference token can't drive the cookie-auth API).
    """
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=settings.inference_token_expire_minutes))
    claims = {
        "sub": user_id,
        "type": "inference",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)


def decode_inference_token(token: str) -> str:
    """Return the subject (user_id) of a valid inference token (Slice 4a).

    Raises ``AuthenticationError`` for any invalid, tampered, expired, or
    wrong-type token (including a regular ``access`` token), so the proxy
    translates it to a 401 uniformly.
    """
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
    except JWTError as exc:
        raise AuthenticationError("Invalid or expired inference token") from exc

    if claims.get("type") != "inference":
        raise AuthenticationError("Wrong token type")
    sub = claims.get("sub")
    if not sub:
        raise AuthenticationError("Token missing subject")
    return sub
