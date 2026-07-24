"""Tests for Sub2API admin probe diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from agentcore.config import settings
from agentcore.llm import sub2api_probe as probe


def _reset_token_cache() -> None:
    probe._cached_token = None
    probe._token_expires_at = 0.0


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    _reset_token_cache()
    yield
    _reset_token_cache()


def test_mask_email():
    assert probe._mask_email("elizabeth@gmail.com") == "eli***@gmail.com"
    assert probe._mask_email("ab@x.com") == "ab***@x.com"


def test_diagnose_account_quota_reset():
    future = datetime.now(UTC) + timedelta(hours=2)
    result = probe._diagnose_account(
        {
            "credentials": {"email": "user@example.com"},
            "extra": {"codex_5h_reset_at": future.isoformat()},
        }
    )
    assert "5 小时使用配额已用完" in result.diagnosis
    assert result.account_email_masked == "use***@example.com"


def test_diagnose_account_oauth_expired():
    past = datetime.now(UTC) - timedelta(hours=1)
    result = probe._diagnose_account(
        {
            "credentials": {"email": "user@example.com", "expires_at": past.isoformat()},
        }
    )
    assert "OAuth token 已过期" in result.diagnosis


def test_diagnose_account_missing_access_token():
    result = probe._diagnose_account(
        {
            "credentials": {"email": "user@example.com"},
            "credentials_status": {"has_access_token": False},
        }
    )
    assert result.diagnosis == "账号未绑定 access token"


@pytest.mark.asyncio
async def test_probe_returns_none_without_admin_url(monkeypatch):
    monkeypatch.setattr(settings, "sub2api_admin_url", "")
    assert await probe.probe_sub2api_diagnosis() is None


@pytest.mark.asyncio
async def test_probe_returns_diagnosis_on_503(monkeypatch):
    future = datetime.now(UTC) + timedelta(hours=1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(
                200,
                json={"data": {"access_token": "admin-token", "expires_in": 3600}},
            )
        if request.url.path.endswith("/admin/accounts"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            {
                                "credentials": {"email": "eli@gmail.com"},
                                "extra": {"codex_5h_reset_at": future.isoformat()},
                            }
                        ]
                    }
                },
            )
        return httpx.Response(404)

    monkeypatch.setattr(settings, "sub2api_admin_url", "http://sub2api.test")
    monkeypatch.setattr(settings, "sub2api_admin_email", "admin@test")
    monkeypatch.setattr(settings, "sub2api_admin_password", "secret")

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(probe.httpx, "AsyncClient", _client_factory)

    diagnosis = await probe.probe_sub2api_diagnosis()
    assert diagnosis is not None
    assert "5 小时使用配额已用完" in diagnosis


@pytest.mark.asyncio
async def test_probe_fail_open_on_admin_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "sub2api_admin_url", "http://sub2api.test")
    monkeypatch.setattr(settings, "sub2api_admin_email", "admin@test")
    monkeypatch.setattr(settings, "sub2api_admin_password", "secret")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"down")

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def _client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(probe.httpx, "AsyncClient", _client_factory)

    assert await probe.probe_sub2api_diagnosis() is None


@pytest.mark.asyncio
async def test_provider_attaches_diagnosis_on_platform_503(monkeypatch):
    from agentcore.core.errors import LLMUpstreamError
    from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
    from agentcore.llm.provider.protocol import LLMMessage, LLMRequest

    future = datetime.now(UTC) + timedelta(hours=1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(
                200,
                json={"data": {"access_token": "admin-token", "expires_in": 3600}},
            )
        if request.url.path.endswith("/admin/accounts"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "items": [
                            {
                                "credentials": {"email": "eli@gmail.com"},
                                "extra": {"codex_5h_reset_at": future.isoformat()},
                            }
                        ]
                    }
                },
            )
        return httpx.Response(503, content=b"upstream unavailable")

    monkeypatch.setattr(settings, "billing_mode", "platform")
    monkeypatch.setattr(settings, "sub2api_admin_url", "http://sub2api.test")
    monkeypatch.setattr(settings, "sub2api_admin_email", "admin@test")
    monkeypatch.setattr(settings, "sub2api_admin_password", "secret")

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatibleProvider(name="platform", api_key="k", base_url="http://llm.test/v1")
    await provider._client.aclose()
    provider._client = httpx.AsyncClient(base_url="http://llm.test/v1", transport=transport)

    probe_transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def _probe_client_factory(*args, **kwargs):
        kwargs["transport"] = probe_transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(probe.httpx, "AsyncClient", _probe_client_factory)

    req = LLMRequest(messages=[LLMMessage(role="user", content="hi")], model="gpt-4o")
    try:
        with pytest.raises(LLMUpstreamError) as ei:
            await provider.complete(req)
        assert "诊断：" in ei.value.message
        assert "5 小时使用配额已用完" in ei.value.message
        assert ei.value.details.get("sub2api_diagnosis")
        assert ei.value.details.get("sub2api_account") == "eli***@gmail.com"
    finally:
        await provider.close()
