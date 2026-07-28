"""Security primitives: password hashing, JWT tokens, CSRF, refresh tokens,
at-rest secret encryption (BYOK API keys).

Split by concern under ``agentcore.security.*``; this package re-exports the
historical flat import path ``from agentcore.security import X``.
"""

from agentcore.security.csrf import sign_csrf_token, verify_csrf_token
from agentcore.security.keys import KeyEncryptor
from agentcore.security.passwords import hash_password, verify_password
from agentcore.security.refresh import (
    generate_invite_code,
    generate_refresh_token,
    generate_temp_password,
    hash_refresh_token,
)
from agentcore.security.tokens import (
    create_access_token,
    create_inference_token,
    create_mfa_pending_token,
    decode_access_token,
    decode_access_token_claims,
    decode_access_token_family,
    decode_access_token_mfa_verified,
    decode_inference_token,
    decode_mfa_pending_token,
)

__all__ = [
    "KeyEncryptor",
    "create_access_token",
    "create_inference_token",
    "create_mfa_pending_token",
    "decode_access_token",
    "decode_access_token_claims",
    "decode_access_token_family",
    "decode_access_token_mfa_verified",
    "decode_inference_token",
    "decode_mfa_pending_token",
    "generate_invite_code",
    "generate_refresh_token",
    "generate_temp_password",
    "hash_password",
    "hash_refresh_token",
    "sign_csrf_token",
    "verify_csrf_token",
    "verify_password",
]
