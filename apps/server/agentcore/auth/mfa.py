"""Admin TOTP MFA: enrollment, verification, recovery codes."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

import pyotp

from agentcore.config import settings
from agentcore.core.errors import AuthenticationError, ValidationError
from agentcore.db.repositories.admin_mfa import AdminMfaRepository
from agentcore.security.keys import KeyEncryptor


def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _encryptor() -> KeyEncryptor | None:
    if not settings.encryption_key:
        return None
    return KeyEncryptor(settings.encryption_key)


@dataclass(frozen=True)
class MfaSetupPayload:
    secret: str
    otpauth_uri: str


@dataclass(frozen=True)
class MfaConfirmResult:
    recovery_codes: list[str]


class AdminMfaService:
    def __init__(self, *, mfa_repo: AdminMfaRepository) -> None:
        self._mfa = mfa_repo

    async def is_enrolled(self, user_id: str) -> bool:
        row = await self._mfa.get_by_user_id(user_id)
        return row is not None and row.enabled_at is not None

    async def begin_setup(self, *, user_id: str, username: str) -> MfaSetupPayload:
        enc = _encryptor()
        if enc is None:
            raise ValidationError("服务器未配置加密密钥，无法启用双因素认证")
        secret = pyotp.random_base32()
        await self._mfa.upsert_pending(
            user_id=user_id,
            totp_secret_enc=enc.encrypt(secret.encode()),
        )
        totp = pyotp.TOTP(secret)
        issuer = settings.mfa_issuer_name
        return MfaSetupPayload(
            secret=secret,
            otpauth_uri=totp.provisioning_uri(name=username, issuer_name=issuer),
        )

    async def confirm_setup(self, *, user_id: str, code: str) -> MfaConfirmResult:
        row = await self._mfa.get_by_user_id(user_id)
        if row is None:
            raise ValidationError("请先开始双因素认证绑定")
        secret = self._decrypt_secret(row.totp_secret_enc)
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            raise AuthenticationError("验证码无效或已过期")
        recovery_codes = [secrets.token_hex(4) for _ in range(8)]
        await self._mfa.enable(
            user_id,
            recovery_codes_hash=[_hash_recovery_code(c) for c in recovery_codes],
        )
        return MfaConfirmResult(recovery_codes=recovery_codes)

    async def verify_code(self, *, user_id: str, code: str) -> bool:
        row = await self._mfa.get_by_user_id(user_id)
        if row is None or row.enabled_at is None:
            return False
        secret = self._decrypt_secret(row.totp_secret_enc)
        return pyotp.TOTP(secret).verify(code, valid_window=1)

    async def verify_recovery_code(self, *, user_id: str, code: str) -> bool:
        normalized = code.strip().replace("-", "").lower()
        if not normalized:
            return False
        return await self._mfa.consume_recovery_code(user_id, _hash_recovery_code(normalized))

    def _decrypt_secret(self, ciphertext: bytes) -> str:
        enc = _encryptor()
        if enc is None:
            raise ValidationError("服务器未配置加密密钥")
        return enc.decrypt(ciphertext).decode()
