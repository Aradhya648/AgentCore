"""P1-2: Admin MFA session proof on access tokens / get_current_admin."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from agentcore.api.dependencies import get_current_admin
from agentcore.config import settings
from agentcore.core.errors import MfaRequiredError, MfaSetupRequiredError
from agentcore.security import (
    create_access_token,
    decode_access_token_mfa_verified,
)
from agentcore.security.tokens import create_mfa_pending_token, decode_mfa_pending_token


def _request(*, mfa_verified: bool) -> Request:
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    req = Request(scope)
    req.state.mfa_verified = mfa_verified
    return req


@pytest.fixture
def admin_user():
    return SimpleNamespace(user_id="admin-1", role="admin", status="active")


@pytest.mark.asyncio
async def test_get_current_admin_rejects_enrolled_without_mfa_claim(
    admin_user, monkeypatch
):
    monkeypatch.setattr(settings, "admin_mfa_required", True)
    mfa_repo = AsyncMock()
    mfa_repo.get_by_user_id.return_value = SimpleNamespace(enabled_at="2026-01-01")
    with pytest.raises(MfaRequiredError):
        await get_current_admin(
            _request(mfa_verified=False), admin_user, mfa_repo=mfa_repo
        )


@pytest.mark.asyncio
async def test_get_current_admin_allows_enrolled_with_mfa_claim(admin_user, monkeypatch):
    monkeypatch.setattr(settings, "admin_mfa_required", True)
    mfa_repo = AsyncMock()
    mfa_repo.get_by_user_id.return_value = SimpleNamespace(enabled_at="2026-01-01")
    out = await get_current_admin(
        _request(mfa_verified=True), admin_user, mfa_repo=mfa_repo
    )
    assert out is admin_user


@pytest.mark.asyncio
async def test_get_current_admin_unenrolled_still_setup_required(admin_user, monkeypatch):
    monkeypatch.setattr(settings, "admin_mfa_required", True)
    mfa_repo = AsyncMock()
    mfa_repo.get_by_user_id.return_value = None
    with pytest.raises(MfaSetupRequiredError):
        await get_current_admin(
            _request(mfa_verified=False), admin_user, mfa_repo=mfa_repo
        )


@pytest.mark.asyncio
async def test_get_current_admin_mfa_disabled_skips_claim(admin_user, monkeypatch):
    """When admin_mfa_required=False, password-only admin sessions stay valid."""
    monkeypatch.setattr(settings, "admin_mfa_required", False)
    mfa_repo = AsyncMock()
    out = await get_current_admin(
        _request(mfa_verified=False), admin_user, mfa_repo=mfa_repo
    )
    assert out is admin_user
    mfa_repo.get_by_user_id.assert_not_called()


def test_access_token_mfa_claim_roundtrip():
    plain = create_access_token("u1", audience="admin", family="f1")
    assert decode_access_token_mfa_verified(plain) is False
    verified = create_access_token(
        "u1", audience="admin", family="f1", mfa_verified=True
    )
    assert decode_access_token_mfa_verified(verified) is True


def test_mfa_pending_token_is_not_access_with_mfa_claim():
    pending = create_mfa_pending_token("u1", audience="admin")
    user_id, aud = decode_mfa_pending_token(pending)
    assert user_id == "u1" and aud == "admin"
    # Pending tokens are a different type; access decoder must refuse them.
    from agentcore.core.errors import AuthenticationError
    from agentcore.security import decode_access_token

    with pytest.raises(AuthenticationError):
        decode_access_token(pending)
