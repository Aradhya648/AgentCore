"""Password hashing (argon2id via pwdlib)."""

from pwdlib import PasswordHash

# Per-hash salt is embedded in the output string.
_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plaintext password (argon2id). Output embeds salt + parameters."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return True iff ``password`` matches the stored hash."""
    return _password_hasher.verify(password, password_hash)
