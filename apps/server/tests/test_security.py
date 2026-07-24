"""Unit tests for security primitives (pure functions, no DB)."""

from datetime import timedelta

import pytest

from agentcore.core.errors import AuthenticationError
from agentcore.security import (
    KeyEncryptor,
    create_access_token,
    decode_access_token,
    decode_access_token_claims,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)

# A valid 64-hex (32-byte) AES-256 master key for the encryptor tests.
_MASTER_KEY = "a" * 64

# --- passwords ---


def test_hash_password_then_verify():
    h = hash_password("s3cret-pw")
    assert h != "s3cret-pw"
    assert verify_password("s3cret-pw", h) is True


def test_verify_password_rejects_wrong():
    h = hash_password("s3cret-pw")
    assert verify_password("nope", h) is False


def test_hash_password_is_salted():
    # Same input must yield different hashes (random per-hash salt).
    assert hash_password("same-input") != hash_password("same-input")


# --- access tokens ---


def test_access_token_roundtrip():
    token = create_access_token("user-123", audience="product", family="fam-abc")
    assert decode_access_token(token) == "user-123"
    assert decode_access_token_claims(token) == ("user-123", "product")
    from agentcore.security import decode_access_token_family

    assert decode_access_token_family(token) == "fam-abc"


def test_access_token_without_fam_still_validates():
    token = create_access_token("user-123", audience="product")
    assert decode_access_token(token) == "user-123"
    from agentcore.security import decode_access_token_family

    assert decode_access_token_family(token) is None


def test_access_token_expired_is_rejected():
    token = create_access_token(
        "user-123", audience="product", expires_delta=timedelta(seconds=-1)
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(token)


def test_access_token_tampered_signature_is_rejected():
    token = create_access_token("user-123", audience="admin")
    header, payload, sig = token.split(".")
    flipped = ("B" if sig[0] != "B" else "C") + sig[1:]
    with pytest.raises(AuthenticationError):
        decode_access_token(f"{header}.{payload}.{flipped}")


def test_decode_garbage_is_rejected():
    with pytest.raises(AuthenticationError):
        decode_access_token("not.a.valid.jwt")


# --- refresh tokens ---


def test_generate_refresh_token_returns_raw_and_matching_hash():
    raw, token_hash = generate_refresh_token()
    assert raw and token_hash
    assert raw != token_hash
    assert hash_refresh_token(raw) == token_hash


def test_refresh_tokens_are_unique():
    raw1, _ = generate_refresh_token()
    raw2, _ = generate_refresh_token()
    assert raw1 != raw2


# --- at-rest encryption (BYOK keys, AES-256-GCM) ---


def test_key_encryptor_roundtrip():
    enc = KeyEncryptor(_MASTER_KEY)
    secret = b"sk-deepseek-abcdef123456"
    assert enc.decrypt(enc.encrypt(secret)) == secret


def test_key_encryptor_uses_fresh_nonce_each_call():
    # Same plaintext must yield different ciphertext (random per-call nonce), so
    # the wire format never leaks equality of two stored keys.
    enc = KeyEncryptor(_MASTER_KEY)
    assert enc.encrypt(b"same") != enc.encrypt(b"same")


def test_key_encryptor_rejects_tampered_ciphertext():
    enc = KeyEncryptor(_MASTER_KEY)
    blob = bytearray(enc.encrypt(b"secret"))
    blob[-1] ^= 0x01  # flip a tag bit
    with pytest.raises(Exception):
        enc.decrypt(bytes(blob))


def test_key_encryptor_rejects_too_short_ciphertext():
    enc = KeyEncryptor(_MASTER_KEY)
    with pytest.raises(ValueError):
        enc.decrypt(b"short")


def test_key_encryptor_rejects_wrong_length_key():
    with pytest.raises(ValueError):
        KeyEncryptor("ab" * 8)  # 8 bytes, not 32


def test_key_encryptor_rejects_non_hex_key():
    with pytest.raises(ValueError, match="64 hex chars"):
        KeyEncryptor("z" * 64)  # right length, not hex


def test_key_encryptor_rejects_odd_length_hex():
    with pytest.raises(ValueError, match="64 hex chars"):
        KeyEncryptor("abcd")  # valid hex chars but wrong length / odd-capable path


def test_key_encryptor_decrypt_fails_with_different_master_key():
    blob = KeyEncryptor(_MASTER_KEY).encrypt(b"secret")
    other = KeyEncryptor("b" * 64)
    with pytest.raises(Exception):
        other.decrypt(blob)
