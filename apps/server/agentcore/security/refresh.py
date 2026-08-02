"""Refresh tokens and admin temp passwords (stdlib crypto)."""

import hashlib
import secrets

# A one-off password handed to a user after an admin reset. Readable (drops the
# ambiguous 0/O/1/l/I) and long enough to clear the registration policy (≥8) with
# margin, so it survives being copied out of the console and typed back in.
_TEMP_PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_TEMP_PASSWORD_LENGTH = 14


def hash_refresh_token(raw: str) -> str:
    """Hash a refresh token for storage.

    Refresh tokens are high-entropy random strings (not user-chosen secrets),
    so a fast cryptographic digest is sufficient and avoids a slow KDF on the
    hot refresh path. Only the hash is ever persisted.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_refresh_token() -> tuple[str, str]:
    """Return ``(raw, hash)``: send ``raw`` to the client, persist ``hash``."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def generate_temp_password() -> str:
    """Return a high-entropy, human-readable one-off password (admin reset)."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(_TEMP_PASSWORD_LENGTH))
