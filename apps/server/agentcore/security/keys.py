"""AES-256-GCM at-rest encryption for BYOK API keys."""

import os
from binascii import Error as BinasciiError
from binascii import unhexlify

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class KeyEncryptor:
    """AES-256-GCM encryptor for at-rest secrets (BYOK API keys).

    Constructed from a 64-hex-char (32-byte) master key so it stays a pure,
    DB-free primitive (the caller reads ``settings.encryption_key``). Raises
    ``ValueError`` on a malformed key, so a misconfigured server fails loudly
    rather than silently storing unreadable ciphertext.

    Wire format: nonce(12B) ‖ ciphertext+tag.
    """

    _NONCE_SIZE = 12

    def __init__(self, hex_key: str) -> None:
        try:
            raw = unhexlify(hex_key)
        except BinasciiError as exc:
            raise ValueError(
                "encryption_key must be 64 hex chars (32 bytes); "
                "got a non-hex or odd-length value"
            ) from exc
        if len(raw) != 32:
            raise ValueError(
                f"encryption_key must be 32 bytes (64 hex chars), got {len(raw)} bytes"
            )
        self._gcm = AESGCM(raw)

    def encrypt(self, plaintext: bytes) -> bytes:
        """Return ``nonce ‖ ciphertext+tag`` (a fresh random nonce each call)."""
        nonce = os.urandom(self._NONCE_SIZE)
        return nonce + self._gcm.encrypt(nonce, plaintext, None)

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Inverse of :meth:`encrypt`; raises on a too-short or tampered input."""
        if len(ciphertext) < self._NONCE_SIZE:
            raise ValueError("ciphertext too short")
        nonce = ciphertext[: self._NONCE_SIZE]
        return self._gcm.decrypt(nonce, ciphertext[self._NONCE_SIZE :], None)
