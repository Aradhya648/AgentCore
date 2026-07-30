"""Unit tests for model-origin billing gate and account default resolution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcore.billing.gate import preflight_llm_credentials
from agentcore.billing.preference import is_platform_available, platform_catalog_visible
from agentcore.config import settings
from agentcore.core.errors import BYOKKeyMissingError, PlatformBillingUnavailableError
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.resolve import resolve_account_default_model, resolve_model_config


def _user(**quota):
    return SimpleNamespace(
        user_id="u1",
        is_unlimited=False,
        quota_daily_tokens=quota.get("daily_tokens"),
        quota_monthly_cost_usd=quota.get("monthly_cost_usd"),
        quota_daily_requests=quota.get("daily_requests"),
    )


def test_is_platform_available_requires_operator_key(monkeypatch):
    # Isolate the default-key path (per-model overrides are covered in
    # tests/test_platform_model_credentials.py): no override, empty key → unavailable.
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    monkeypatch.setattr(settings, "platform_api_key", "")
    assert is_platform_available() is False
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    assert is_platform_available() is True


def test_platform_catalog_visible_dormant_despite_key(monkeypatch):
    """byok + free_tier off + PLATFORM_API_KEY still set → catalog gate closed."""
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    monkeypatch.setattr(settings, "platform_free_tier_enabled", False)
    assert is_platform_available() is True
    assert platform_catalog_visible() is False


def test_platform_catalog_visible_platform_mode_with_key(monkeypatch):
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "platform")
    monkeypatch.setattr(settings, "platform_free_tier_enabled", False)
    assert platform_catalog_visible() is True


def test_platform_catalog_visible_free_tier_with_key(monkeypatch):
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    assert platform_catalog_visible() is True

def _mock_provider_default(monkeypatch, *, user, row):
    """Wire resolve's UserRepository + UserLlmProviderRepository for the default provider."""
    monkeypatch.setattr(
        "agentcore.db.repositories.UserRepository",
        lambda _s: SimpleNamespace(get_by_id=AsyncMock(return_value=user)),
    )
    monkeypatch.setattr(
        "agentcore.db.repositories.UserLlmProviderRepository",
        lambda _s: SimpleNamespace(
            get=AsyncMock(return_value=row),
            first_for_user=AsyncMock(return_value=row),
            count_for_user=AsyncMock(return_value=1 if row is not None else 0),
        ),
    )


def _prov_row(**kw):
    defaults = {
        "id": "p1",
        "user_id": "u1",
        "default_model": "my-model",
        "api_key_enc": b"x",
        "base_url": "https://user.example/v1",
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


@pytest.mark.asyncio
async def test_resolve_account_default_with_provider(monkeypatch):
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="p",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="my-model", origin="byok", provider_id="p1"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )
    sel = await resolve_account_default_model(MagicMock(), "u1")
    assert sel.model == "my-model"
    assert sel.origin == "byok"
    assert sel.provider_id == "p1"


@pytest.mark.asyncio
async def test_resolve_account_default_without_provider(monkeypatch):
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="bal",
        name="5.2",
        kind="system",
        main=ModelSelection(model="plat-model", origin="platform", provider_id=None),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )
    sel = await resolve_account_default_model(MagicMock(), "u1")
    assert sel.model == "plat-model"
    assert sel.origin == "platform"
    assert sel.provider_id is None


@pytest.mark.asyncio
async def test_resolve_model_config_prefers_provider(monkeypatch):
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "platform_model", "gpt-5")
    row = _prov_row(default_model="user-flash")
    user_creds = LLMCredentials(
        api_key="sk-user",
        base_url="https://user.example/v1",
        default_model="user-flash",
        source="user",
        provider_id="p1",
    )
    expanded = ExpandedProfile(
        profile_id="p",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="user-flash", origin="byok", provider_id="p1"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )
    monkeypatch.setattr(
        "agentcore.db.repositories.UserLlmProviderRepository",
        lambda _s: SimpleNamespace(
            get=AsyncMock(return_value=row),
            first_for_user=AsyncMock(return_value=row),
        ),
    )
    monkeypatch.setattr("agentcore.llm.resolve._decrypt_provider", lambda _r, _u: user_creds)
    cfg = await resolve_model_config(MagicMock(), "u1", "chat")
    assert cfg is not None
    assert cfg.source == "byok"
    assert cfg.model == "user-flash"


@pytest.mark.asyncio
async def test_gate_byok_origin_requires_key():
    with (
        patch(
            "agentcore.billing.gate.resolve_user_llm_credentials",
            AsyncMock(return_value=None),
        ),
        pytest.raises(BYOKKeyMissingError),
    ):
        await preflight_llm_credentials(
            session=MagicMock(),
            user=_user(),
            cost_repo=MagicMock(),
            byok_missing_message="missing",
            model_origin="byok",
        )


@pytest.mark.asyncio
async def test_gate_byok_origin_skips_quota(monkeypatch):
    creds = LLMCredentials(api_key="sk-user", base_url="u", default_model="flash")
    with patch(
        "agentcore.billing.gate.resolve_user_llm_credentials",
        AsyncMock(return_value=creds),
    ):
        result = await preflight_llm_credentials(
            session=MagicMock(),
            user=_user(),
            cost_repo=MagicMock(),
            byok_missing_message="missing",
            model_origin="byok",
        )
    assert result is creds


@pytest.mark.asyncio
async def test_gate_platform_origin_enforces_quota(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    with (
        patch(
            "agentcore.billing.gate.user_has_provider",
            AsyncMock(return_value=False),
        ),
        patch("agentcore.billing.gate.enforce_quota", AsyncMock()) as enforce,
    ):
        result = await preflight_llm_credentials(
            session=MagicMock(),
            user=_user(),
            cost_repo=MagicMock(),
            byok_missing_message="missing",
            model_origin="platform",
        )
    assert result is None
    enforce.assert_awaited_once()
    assert enforce.await_args.kwargs["free_tier"] is True


@pytest.mark.asyncio
async def test_resolve_and_gate_background_platform_enforces_quota(monkeypatch):
    from agentcore.billing.gate import resolve_and_gate_background
    from agentcore.llm.resolve import ModelConfig

    monkeypatch.setattr(settings, "billing_mode", "platform")
    cfg = ModelConfig(
        model="flash",
        base_url="https://p.example/v1",
        api_key="sk-platform",
        source="platform",
        purpose="title",
    )
    with (
        patch(
            "agentcore.billing.gate.resolve_model_config",
            AsyncMock(return_value=cfg),
        ),
        patch("agentcore.billing.gate.platform_catalog_visible", return_value=True),
        patch(
            "agentcore.billing.gate.UserRepository",
            lambda _s: SimpleNamespace(get_by_id=AsyncMock(return_value=_user())),
        ),
        patch(
            "agentcore.billing.gate.user_has_provider",
            AsyncMock(return_value=True),
        ),
        patch("agentcore.billing.gate.enforce_quota", AsyncMock()) as enforce,
    ):
        result = await resolve_and_gate_background(MagicMock(), "u1", purpose="title")
    assert result is not None
    assert result.source == "platform"
    assert result.api_key == "sk-platform"
    enforce.assert_awaited_once()
    assert enforce.await_args.kwargs["free_tier"] is False


@pytest.mark.asyncio
async def test_resolve_and_gate_background_quota_exceeded_returns_none(monkeypatch):
    from agentcore.billing.gate import resolve_and_gate_background
    from agentcore.core.errors import QuotaExceededError
    from agentcore.llm.resolve import ModelConfig

    monkeypatch.setattr(settings, "billing_mode", "platform")
    cfg = ModelConfig(
        model="flash",
        base_url="https://p.example/v1",
        api_key="sk-platform",
        source="platform",
        purpose="title",
    )
    with (
        patch(
            "agentcore.billing.gate.resolve_model_config",
            AsyncMock(return_value=cfg),
        ),
        patch("agentcore.billing.gate.platform_catalog_visible", return_value=True),
        patch(
            "agentcore.billing.gate.UserRepository",
            lambda _s: SimpleNamespace(get_by_id=AsyncMock(return_value=_user())),
        ),
        patch(
            "agentcore.billing.gate.user_has_provider",
            AsyncMock(return_value=True),
        ),
        patch(
            "agentcore.billing.gate.enforce_quota",
            AsyncMock(side_effect=QuotaExceededError("exhausted")),
        ),
    ):
        result = await resolve_and_gate_background(MagicMock(), "u1", purpose="memory")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_and_gate_background_byok_fallback_skips_quota(monkeypatch):
    from agentcore.billing.gate import resolve_and_gate_background
    from agentcore.llm.resolve import ModelConfig

    cfg = ModelConfig(
        model="user-flash",
        base_url="https://user.example/v1",
        api_key="sk-user",
        source="byok",
        purpose="title",
        provider_id="p1",
    )
    with (
        patch(
            "agentcore.billing.gate.resolve_model_config",
            AsyncMock(return_value=cfg),
        ),
        patch("agentcore.billing.gate.enforce_quota", AsyncMock()) as enforce,
    ):
        result = await resolve_and_gate_background(MagicMock(), "u1", purpose="title")
    assert result is not None
    assert result.source == "user"
    assert result.api_key == "sk-user"
    enforce.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_background_llm_platform_auth_falls_back_to_byok(monkeypatch):
    from agentcore.billing.gate import BackgroundLlmResult, run_background_llm
    from agentcore.core.errors import LLMAuthError
    from agentcore.llm.credentials import LLMCredentials

    platform = LLMCredentials(
        api_key="sk-platform",
        base_url="https://p.example/v1",
        default_model="flash",
        source="platform",
    )
    byok = LLMCredentials(
        api_key="sk-user",
        base_url="https://user.example/v1",
        default_model="user-flash",
        source="user",
        provider_id="p1",
    )
    calls: list[str] = []

    async def _runner(creds: LLMCredentials) -> str:
        calls.append(creds.source)
        if creds.source == "platform":
            raise LLMAuthError(provider_name="platform")
        return "ok"

    class _CM:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr("agentcore.billing.gate.async_session_factory", lambda: _CM())
    monkeypatch.setattr(
        "agentcore.billing.gate.resolve_and_gate_background",
        AsyncMock(return_value=platform),
    )
    monkeypatch.setattr(
        "agentcore.billing.gate.resolve_and_gate_background_user_fallback",
        AsyncMock(return_value=byok),
    )

    result = await run_background_llm("u1", purpose="title", runner=_runner)
    assert isinstance(result, BackgroundLlmResult)
    assert result.value == "ok"
    assert result.credentials is byok
    assert calls == ["platform", "user"]


@pytest.mark.asyncio
async def test_run_background_llm_no_byok_after_platform_auth_returns_none(monkeypatch):
    from agentcore.billing.gate import run_background_llm
    from agentcore.core.errors import LLMAuthError
    from agentcore.llm.credentials import LLMCredentials

    platform = LLMCredentials(
        api_key="sk-platform",
        base_url="https://p.example/v1",
        default_model="flash",
        source="platform",
    )

    async def _runner(creds: LLMCredentials) -> str:
        raise LLMAuthError(provider_name="platform")

    class _CM:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr("agentcore.billing.gate.async_session_factory", lambda: _CM())
    monkeypatch.setattr(
        "agentcore.billing.gate.resolve_and_gate_background",
        AsyncMock(return_value=platform),
    )
    monkeypatch.setattr(
        "agentcore.billing.gate.resolve_and_gate_background_user_fallback",
        AsyncMock(return_value=None),
    )

    result = await run_background_llm("u1", purpose="memory", runner=_runner)
    assert result is None


@pytest.mark.asyncio
async def test_run_background_llm_byok_auth_does_not_retry_platform(monkeypatch):
    from agentcore.billing.gate import run_background_llm
    from agentcore.core.errors import LLMAuthError
    from agentcore.llm.credentials import LLMCredentials

    byok = LLMCredentials(
        api_key="sk-user",
        base_url="https://user.example/v1",
        default_model="user-flash",
        source="user",
        provider_id="p1",
    )
    calls: list[str] = []
    fallback = AsyncMock(return_value=None)

    async def _runner(creds: LLMCredentials) -> str:
        calls.append(creds.source)
        raise LLMAuthError(provider_name="byok")

    class _CM:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr("agentcore.billing.gate.async_session_factory", lambda: _CM())
    monkeypatch.setattr(
        "agentcore.billing.gate.resolve_and_gate_background",
        AsyncMock(return_value=byok),
    )
    monkeypatch.setattr(
        "agentcore.billing.gate.resolve_and_gate_background_user_fallback",
        fallback,
    )

    result = await run_background_llm("u1", purpose="title", runner=_runner)
    assert result is None
    assert calls == ["user"]
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_and_gate_background_user_fallback_skips_quota(monkeypatch):
    from agentcore.billing.gate import resolve_and_gate_background_user_fallback
    from agentcore.llm.resolve import ModelConfig

    cfg = ModelConfig(
        model="user-flash",
        base_url="https://user.example/v1",
        api_key="sk-user",
        source="byok",
        purpose="title",
        provider_id="p1",
    )
    with (
        patch(
            "agentcore.billing.gate.resolve_background_user_fallback",
            AsyncMock(return_value=cfg),
        ),
        patch("agentcore.billing.gate.enforce_quota", AsyncMock()) as enforce,
    ):
        result = await resolve_and_gate_background_user_fallback(
            MagicMock(), "u1", purpose="title"
        )
    assert result is not None
    assert result.source == "user"
    enforce.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_platform_origin_dormant_refuses(monkeypatch):
    """byok + free_tier off + key still present → platform origin refused."""
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    monkeypatch.setattr(settings, "platform_free_tier_enabled", False)
    with pytest.raises(PlatformBillingUnavailableError):
        await preflight_llm_credentials(
            session=MagicMock(),
            user=_user(),
            cost_repo=MagicMock(),
            byok_missing_message="missing",
            model_origin="platform",
        )


@pytest.mark.asyncio
async def test_resolve_and_gate_background_dormant_falls_to_byok(monkeypatch):
    """Dormant catalog gate: platform cfg from resolve → BYOK fallback path."""
    from agentcore.billing.gate import resolve_and_gate_background
    from agentcore.llm.resolve import ModelConfig

    platform_cfg = ModelConfig(
        model="flash",
        base_url="https://p.example/v1",
        api_key="sk-platform",
        source="platform",
        purpose="title",
    )
    byok = LLMCredentials(
        api_key="sk-user",
        base_url="https://user.example/v1",
        default_model="user-flash",
        source="user",
        provider_id="p1",
    )
    with (
        patch(
            "agentcore.billing.gate.resolve_model_config",
            AsyncMock(return_value=platform_cfg),
        ),
        patch("agentcore.billing.gate.platform_catalog_visible", return_value=False),
        patch(
            "agentcore.billing.gate.resolve_and_gate_background_user_fallback",
            AsyncMock(return_value=byok),
        ) as fallback,
        patch("agentcore.billing.gate.enforce_quota", AsyncMock()) as enforce,
    ):
        result = await resolve_and_gate_background(MagicMock(), "u1", purpose="title")
    assert result is byok
    fallback.assert_awaited_once()
    enforce.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_model_config_background_dormant_skips_platform(monkeypatch):
    """Background resolve must not return platform when catalog gate is closed."""
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    monkeypatch.setattr(settings, "platform_model", "plat-model")
    monkeypatch.setattr(settings, "platform_background_model", "")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    monkeypatch.setattr(settings, "platform_free_tier_enabled", False)
    monkeypatch.setattr(
        "agentcore.llm.resolve.resolve_background_user_fallback",
        AsyncMock(return_value=None),
    )
    cfg = await resolve_model_config(MagicMock(), "u1", "title")
    assert cfg is None
