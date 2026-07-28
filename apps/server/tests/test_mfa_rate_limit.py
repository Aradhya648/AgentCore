"""P1-3: Admin MFA TOTP/recovery verify rate limiting."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pyotp
import pytest

from agentcore.auth.mfa import AdminMfaService
from agentcore.auth.mfa_rate_limit import enforce_mfa_verify_rate_limit
from agentcore.config import settings
from agentcore.core.errors import AuthenticationError, RateLimitedError
from agentcore.middleware.rate_limit import SlidingWindowRateLimiter
from agentcore.security.keys import KeyEncryptor

_MASTER_KEY = "a" * 64


@pytest.fixture(autouse=True)
def _mfa_rate_limit_on(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "mfa_verify_rate_limit_max", 5)
    monkeypatch.setattr(settings, "mfa_verify_rate_limit_window_seconds", 30)


# --- enforce_mfa_verify_rate_limit ---


async def test_enforce_mfa_passes_under_limit():
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    await enforce_mfa_verify_rate_limit("u", limiter=limiter, now=0)
    await enforce_mfa_verify_rate_limit("u", limiter=limiter, now=0)


async def test_enforce_mfa_raises_when_over(monkeypatch):
    monkeypatch.setattr(settings, "mfa_verify_rate_limit_max", 20)
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    await enforce_mfa_verify_rate_limit("u", limiter=limiter, now=0)
    with pytest.raises(RateLimitedError) as ei:
        await enforce_mfa_verify_rate_limit("u", limiter=limiter, now=4)
    assert ei.value.code == "RATE_LIMITED"
    assert ei.value.status_code == 429
    assert ei.value.retry_after == 6


async def test_enforce_mfa_noop_when_dimension_disabled(monkeypatch):
    monkeypatch.setattr(settings, "mfa_verify_rate_limit_max", 0)
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    limiter.check("u", now=0)
    await enforce_mfa_verify_rate_limit("u", limiter=limiter, now=0)


async def test_enforce_mfa_noop_when_globally_off(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=10)
    limiter.check("u", now=0)
    await enforce_mfa_verify_rate_limit("u", limiter=limiter, now=0)


# --- AdminMfaService write paths ---


def _enrolled_service(monkeypatch, *, secret: str | None = None):
    monkeypatch.setattr(settings, "encryption_key", _MASTER_KEY)
    enc = KeyEncryptor(_MASTER_KEY)
    totp_secret = secret or pyotp.random_base32()
    row = SimpleNamespace(
        totp_secret_enc=enc.encrypt(totp_secret.encode()),
        enabled_at="2026-01-01",
    )
    repo = AsyncMock()
    repo.get_by_user_id = AsyncMock(return_value=row)
    repo.consume_recovery_code = AsyncMock(return_value=False)
    repo.enable = AsyncMock()
    return AdminMfaService(mfa_repo=repo), totp_secret, repo


async def test_verify_code_success_unaffected(monkeypatch):
    svc, secret, _repo = _enrolled_service(monkeypatch)
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=30)
    monkeypatch.setattr(
        "agentcore.auth.mfa_rate_limit.mfa_verify_rate_limiter",
        limiter,
    )
    code = pyotp.TOTP(secret).now()
    assert await svc.verify_code(user_id="admin-1", code=code) is True


async def test_verify_code_blocks_after_attempt_budget(monkeypatch):
    svc, _secret, repo = _enrolled_service(monkeypatch)
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=30)
    monkeypatch.setattr(
        "agentcore.auth.mfa_rate_limit.mfa_verify_rate_limiter",
        limiter,
    )
    for _ in range(3):
        assert await svc.verify_code(user_id="admin-1", code="000000") is False
    with pytest.raises(RateLimitedError):
        await svc.verify_code(user_id="admin-1", code="000000")
    # Locked path must not keep hitting crypto / repo decrypt work beyond the gate.
    assert repo.get_by_user_id.await_count == 3


async def test_confirm_setup_blocks_after_attempt_budget(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", _MASTER_KEY)
    enc = KeyEncryptor(_MASTER_KEY)
    secret = pyotp.random_base32()
    row = SimpleNamespace(totp_secret_enc=enc.encrypt(secret.encode()), enabled_at=None)
    repo = AsyncMock()
    repo.get_by_user_id = AsyncMock(return_value=row)
    repo.enable = AsyncMock()
    svc = AdminMfaService(mfa_repo=repo)

    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=30)
    monkeypatch.setattr(
        "agentcore.auth.mfa_rate_limit.mfa_verify_rate_limiter",
        limiter,
    )
    with pytest.raises(AuthenticationError):
        await svc.confirm_setup(user_id="admin-2", code="000000")
    with pytest.raises(AuthenticationError):
        await svc.confirm_setup(user_id="admin-2", code="000000")
    with pytest.raises(RateLimitedError):
        await svc.confirm_setup(user_id="admin-2", code="000000")


async def test_confirm_setup_success_under_limit(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", _MASTER_KEY)
    enc = KeyEncryptor(_MASTER_KEY)
    secret = pyotp.random_base32()
    row = SimpleNamespace(totp_secret_enc=enc.encrypt(secret.encode()), enabled_at=None)
    repo = AsyncMock()
    repo.get_by_user_id = AsyncMock(return_value=row)
    repo.enable = AsyncMock()
    svc = AdminMfaService(mfa_repo=repo)
    limiter = SlidingWindowRateLimiter(max_requests=5, window_seconds=30)
    monkeypatch.setattr(
        "agentcore.auth.mfa_rate_limit.mfa_verify_rate_limiter",
        limiter,
    )
    result = await svc.confirm_setup(user_id="admin-3", code=pyotp.TOTP(secret).now())
    assert len(result.recovery_codes) == 8
    repo.enable.assert_awaited_once()


async def test_verify_recovery_code_rate_limited(monkeypatch):
    svc, _secret, repo = _enrolled_service(monkeypatch)
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=30)
    monkeypatch.setattr(
        "agentcore.auth.mfa_rate_limit.mfa_verify_rate_limiter",
        limiter,
    )
    assert await svc.verify_recovery_code(user_id="admin-4", code="deadbeef") is False
    with pytest.raises(RateLimitedError):
        await svc.verify_recovery_code(user_id="admin-4", code="deadbeef")
    assert repo.consume_recovery_code.await_count == 1
