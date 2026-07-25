"""Free-tier (platform-paid fallback) + call-level credential_source pricing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcore.billing.gate import preflight_llm_credentials
from agentcore.billing.preference import is_free_tier_active
from agentcore.config import settings
from agentcore.conversation.quota import QuotaLimits, enforce_quota
from agentcore.core.error_codes import ErrorCode
from agentcore.core.errors import BYOKKeyMissingError, FreeTierExhaustedError, QuotaExceededError
from agentcore.llm.pricing import (
    DOUBAO_SEED_TURBO,
    NANO_PER_USD,
    calculate_cost,
    resolve_credential_source,
)
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.llm.resolve import resolve_model_config
from agentcore.runtime.costing import priced_call_cost

_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _usage(**kw: int) -> TokenUsage:
    return TokenUsage(**kw)


def _agg(*, input_: int = 0, output: int = 0, turns: int = 0, cost_total: int = 0) -> dict:
    return {
        "usage": {
            "input": input_,
            "output": output,
            "reasoning": 0,
            "cache_hit": 0,
            "cache_miss": 0,
        },
        "cost": {"input": 0, "cached": 0, "output": 0, "total": cost_total},
        "rounds": 0,
        "turns": turns,
    }


class _FakeRepo:
    def __init__(self, *, today: dict | None = None, month: dict | None = None):
        self._today = today or _agg()
        self._month = month or _agg()

    async def aggregate_for_window(self, *, user_id: str, since: datetime) -> dict:
        return self._month if since.day == 1 else self._today


def _user(**quota):
    return SimpleNamespace(
        user_id="u1",
        is_unlimited=False,
        quota_daily_tokens=quota.get("daily_tokens"),
        quota_monthly_cost_usd=quota.get("monthly_cost_usd"),
        quota_daily_requests=quota.get("daily_requests"),
    )


# --- call-level pricing (F2 / F7) ---


def test_user_credential_source_estimate_not_billed():
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000, output_tokens=1000)
    cost = calculate_cost(DEEPSEEK_V4_FLASH, usage, credential_source="user")
    # Community estimate may be >0; ledger split keeps cost_total_nano at 0.
    assert cost.credential_source == "user"
    assert cost.pricing_source in ("estimated", "user_defined", "unpriced")
    from agentcore.runtime.costing import priced_call_cost

    row = priced_call_cost(
        model=DEEPSEEK_V4_FLASH, usage=usage, role="captain", credential_source="user"
    )
    assert row.cost_total_nano == 0


def test_platform_credential_source_real_price_ignores_deployment_byok(monkeypatch):
    monkeypatch.setattr(settings, "billing_mode", "byok")
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000)
    cost = calculate_cost(DEEPSEEK_V4_FLASH, usage, credential_source="platform")
    assert cost.total > 0


def test_vendor_extras_call_real_price_under_byok_deployment(monkeypatch):
    """F7: doubao/ extras are platform money — must price even when deployment is byok."""
    monkeypatch.setattr(settings, "billing_mode", "byok")
    usage = _usage(input_tokens=1_000_000, cache_miss_tokens=1_000_000, output_tokens=1_000_000)
    cost = calculate_cost(DOUBAO_SEED_TURBO, usage, credential_source="vendor")
    assert cost.total > 0
    # Model prefix alone also forces vendor pricing (ambient user must not zero it).
    prefixed = calculate_cost(
        DOUBAO_SEED_TURBO, usage, credential_source="user"
    )
    # explicit user wins over model prefix when credential_source is passed
    assert prefixed.credential_source == "user"
    assert prefixed.pricing_source in ("estimated", "unpriced", "user_defined")
    via_prefix = calculate_cost(DOUBAO_SEED_TURBO, usage)
    # no ambient → platform default, but model prefix → vendor → real price
    assert via_prefix.total > 0
    assert resolve_credential_source(model=DOUBAO_SEED_TURBO) == "vendor"


def test_priced_call_cost_respects_credential_source(monkeypatch):
    monkeypatch.setattr(settings, "billing_mode", "byok")
    usage = _usage(input_tokens=10_000, cache_miss_tokens=10_000, output_tokens=100)
    byok = priced_call_cost(
        model=DEEPSEEK_V4_FLASH, usage=usage, role="captain", credential_source="user"
    )
    platform = priced_call_cost(
        model=DEEPSEEK_V4_FLASH, usage=usage, role="captain", credential_source="platform"
    )
    assert byok.cost_total_nano == 0
    assert byok.cost_estimated_nano >= 0
    assert platform.cost_total_nano > 0
    assert platform.cost_estimated_nano == 0


# --- gate fallback ---


@pytest.mark.asyncio
async def test_gate_byok_missing_key_402_when_free_tier_off(monkeypatch):
    monkeypatch.setattr(settings, "platform_free_tier_enabled", False)
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    user = _user()
    with (
        patch(
            "agentcore.billing.gate.resolve_user_llm_credentials",
            AsyncMock(return_value=None),
        ),
        pytest.raises(BYOKKeyMissingError) as ei,
    ):
        await preflight_llm_credentials(
            session=MagicMock(),
            user=user,
            cost_repo=_FakeRepo(),
            byok_missing_message="missing",
            model_origin="byok",
        )
    assert ei.value.status_code == 402


@pytest.mark.asyncio
async def test_gate_free_tier_fallback_to_platform(monkeypatch):
    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    user = _user()
    with patch(
        "agentcore.billing.gate.user_has_provider",
        AsyncMock(return_value=False),
    ):
        result = await preflight_llm_credentials(
            session=MagicMock(),
            user=user,
            cost_repo=_FakeRepo(),
            byok_missing_message="missing",
            model_origin="platform",
        )
    assert result is None  # platform-paid path


@pytest.mark.asyncio
async def test_gate_free_tier_exhausted_returns_dedicated_code(monkeypatch):
    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    monkeypatch.setattr(settings, "free_tier_monthly_cost_usd", 0.14)
    user = _user()
    repo = _FakeRepo(month=_agg(cost_total=int(0.14 * NANO_PER_USD)))
    with (
        patch(
            "agentcore.billing.gate.user_has_provider",
            AsyncMock(return_value=False),
        ),
        pytest.raises(FreeTierExhaustedError) as ei,
    ):
        await preflight_llm_credentials(
            session=MagicMock(),
            user=user,
            cost_repo=repo,
            byok_missing_message="missing",
            model_origin="platform",
        )
    assert ei.value.code == ErrorCode.FREE_TIER_EXHAUSTED
    assert ei.value.status_code == 429
    assert "免费额度" in ei.value.message
    assert "自己的模型" in ei.value.message


@pytest.mark.asyncio
async def test_gate_with_user_key_skips_quota(monkeypatch):
    """有 key 用户零变化：不查配额、返回用户凭据。"""
    from agentcore.llm.credentials import LLMCredentials

    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    creds = LLMCredentials(
        api_key="sk-user", base_url="https://api.deepseek.com", default_model="flash"
    )
    with patch(
        "agentcore.billing.gate.resolve_user_llm_credentials",
        AsyncMock(return_value=creds),
    ):
        result = await preflight_llm_credentials(
            session=MagicMock(),
            user=_user(),
            cost_repo=_FakeRepo(month=_agg(cost_total=10**18)),
            byok_missing_message="missing",
            model_origin="byok",
        )
    assert result is creds


# --- D7 limits ---


def test_free_tier_defaults_used_on_byok_platform_path():
    limits = QuotaLimits.for_user(_user(), use_free_tier_defaults=True)
    assert limits.daily_tokens == settings.free_tier_daily_tokens
    assert limits.daily_requests == settings.free_tier_daily_requests
    assert limits.monthly_cost_nano == int(settings.free_tier_monthly_cost_usd * NANO_PER_USD)


def test_global_quota_defaults_when_not_free_tier():
    limits = QuotaLimits.for_user(_user(), use_free_tier_defaults=False)
    assert limits == QuotaLimits.from_settings(use_free_tier_defaults=False)


@pytest.mark.asyncio
async def test_enforce_quota_free_tier_flag_uses_conversion_message():
    repo = _FakeRepo(today=_agg(input_=200_000, output=0, turns=1))
    limits = QuotaLimits(daily_tokens=200_000, monthly_cost_nano=0, daily_requests=0)
    with pytest.raises(FreeTierExhaustedError) as ei:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits, free_tier=True)
    assert ei.value.code == ErrorCode.FREE_TIER_EXHAUSTED
    # Non-free-tier path keeps QUOTA_EXCEEDED semantics.
    with pytest.raises(QuotaExceededError) as ei2:
        await enforce_quota(repo, "u1", now=_NOW, limits=limits, free_tier=False)
    assert ei2.value.code == ErrorCode.QUOTA_EXCEEDED
    assert not isinstance(ei2.value, FreeTierExhaustedError)


# --- D6 background purpose priority ---


def _byok_user(**kw):
    defaults = {
        "user_id": "u1",
        "default_model_profile_id": "prof-1",
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _provider_row(**kw):
    defaults = {
        "id": "p1",
        "user_id": "u1",
        "default_model": "user-flash",
        "api_key_enc": b"x",
        "base_url": "https://user.example/v1",
        "price_cache_hit": None,
        "price_cache_miss": None,
        "price_output": None,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _mock_provider_repos(monkeypatch, *, user, row):
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


@pytest.mark.asyncio
async def test_background_prefers_platform_even_with_byok(monkeypatch):
    """Product chrome is platform-first; chat stays BYOK when the user has a key."""
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "platform_model", "platform-flash")
    monkeypatch.setattr(settings, "platform_background_model", "")
    user_creds = LLMCredentials(
        api_key="sk-user",
        base_url="https://user.example/v1",
        default_model="user-flash",
        source="user",
        provider_id="p1",
    )
    expanded = ExpandedProfile(
        profile_id="prof-1",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="user-flash", origin="byok", provider_id="p1"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )
    session = MagicMock()
    _mock_provider_repos(monkeypatch, user=_byok_user(), row=_provider_row())
    monkeypatch.setattr(
        "agentcore.llm.resolve._decrypt_provider", lambda _row, _uid: user_creds
    )
    for purpose in ("title", "memory", "compaction", "followups"):
        cfg = await resolve_model_config(session, "u1", purpose)
        assert cfg is not None
        assert cfg.source == "platform"
        assert cfg.api_key == "sk-platform"
        assert cfg.model == "platform-flash"
    chat = await resolve_model_config(session, "u1", "chat")
    assert chat is not None
    assert chat.source == "byok"
    assert chat.api_key == "sk-user"


@pytest.mark.asyncio
async def test_d6_background_falls_back_to_platform_when_no_key(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "platform_model", "platform-flash")
    session = MagicMock()
    _mock_provider_repos(
        monkeypatch,
        user=_byok_user(default_model_profile_id=None),
        row=None,
    )
    cfg = await resolve_model_config(session, "u1", "title")
    assert cfg is not None
    assert cfg.source == "platform"
    assert cfg.api_key == "sk-platform"


@pytest.mark.asyncio
async def test_background_falls_back_to_byok_when_platform_missing(monkeypatch):
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    monkeypatch.setattr(settings, "platform_api_key", "")
    monkeypatch.setattr(settings, "platform_model", "platform-flash")
    user_creds = LLMCredentials(
        api_key="sk-user",
        base_url="https://user.example/v1",
        default_model="user-flash",
        source="user",
        provider_id="p1",
    )
    expanded = ExpandedProfile(
        profile_id="prof-1",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="user-flash", origin="byok", provider_id="p1"),
        background=ModelSelection(model="user-flash", origin="byok", provider_id="p1"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )
    session = MagicMock()
    _mock_provider_repos(monkeypatch, user=_byok_user(), row=_provider_row())
    monkeypatch.setattr(
        "agentcore.llm.resolve._decrypt_provider", lambda _row, _uid: user_creds
    )
    cfg = await resolve_model_config(session, "u1", "title")
    assert cfg is not None
    assert cfg.source == "byok"
    assert cfg.api_key == "sk-user"


# --- free_tier_active signal ---


def test_free_tier_active_requires_all_three(monkeypatch):
    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    assert is_free_tier_active(has_user_key=False) is True
    assert is_free_tier_active(has_user_key=True) is False
    monkeypatch.setattr(settings, "platform_free_tier_enabled", False)
    assert is_free_tier_active(has_user_key=False) is False


@pytest.mark.asyncio
async def test_llm_providers_status_exposes_free_tier_active(monkeypatch):
    from agentcore.llm.provider_service import LlmProviderService

    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    service = LlmProviderService(MagicMock())
    service._users = MagicMock()
    service._users.get_by_id = AsyncMock(
        return_value=SimpleNamespace(user_id="u1", default_model_profile_id=None)
    )
    service._repo = MagicMock()
    service._repo.list_for_user = AsyncMock(return_value=[])  # keyless
    view = await service.list_providers("u1")
    assert view.free_tier_active is True
    assert view.providers == []
    assert view.default_model_profile_id is None


@pytest.mark.asyncio
async def test_proxy_quota_exceeded_returns_429_not_402(monkeypatch):
    """F8 fix: proxy must map QuotaExceededError to HTTP 429 (not 402)."""
    from agentcore.api.routes import inference

    async def _boom(**_kwargs):
        raise QuotaExceededError("over", dimension="monthly_cost", used=1, limit=1)

    monkeypatch.setattr(inference.proxy, "preflight_llm_credentials", _boom)
    monkeypatch.setattr(
        "agentcore.llm.resolve.resolve_account_default_model",
        AsyncMock(
            return_value=SimpleNamespace(model="flash", origin="platform", provider_id=None)
        ),
    )

    async def _noop_rate(_user_id, message_id=None):
        return None

    monkeypatch.setattr(
        inference.proxy, "enforce_inference_proxy_rate_limit", _noop_rate
    )

    class _Req:
        async def json(self):
            return {"messages": [{"role": "user", "content": "hi"}], "stream": False}

        headers: dict = {}

    resp = await inference.proxy.inference_chat_completions(
        request=_Req(),  # type: ignore[arg-type]
        user=_user(),  # type: ignore[arg-type]
        session=MagicMock(),
        cost_repo=MagicMock(),
    )
    assert resp.status_code == 429
    body = json.loads(resp.body)
    assert body["error"]["code"] == ErrorCode.QUOTA_EXCEEDED


@pytest.mark.asyncio
async def test_proxy_free_tier_exhausted_returns_429_with_code(monkeypatch):
    from agentcore.api.routes import inference

    async def _boom(**_kwargs):
        raise FreeTierExhaustedError(dimension="monthly_cost", used=1, limit=1)

    monkeypatch.setattr(inference.proxy, "preflight_llm_credentials", _boom)
    monkeypatch.setattr(
        "agentcore.llm.resolve.resolve_account_default_model",
        AsyncMock(
            return_value=SimpleNamespace(model="flash", origin="platform", provider_id=None)
        ),
    )

    async def _noop_rate(_user_id, message_id=None):
        return None

    monkeypatch.setattr(
        inference.proxy, "enforce_inference_proxy_rate_limit", _noop_rate
    )

    class _Req:
        async def json(self):
            return {"messages": [{"role": "user", "content": "hi"}], "stream": False}

        headers: dict = {}

    resp = await inference.proxy.inference_chat_completions(
        request=_Req(),  # type: ignore[arg-type]
        user=_user(),  # type: ignore[arg-type]
        session=MagicMock(),
        cost_repo=MagicMock(),
    )
    assert resp.status_code == 429
    body = json.loads(resp.body)
    assert body["error"]["code"] == ErrorCode.FREE_TIER_EXHAUSTED
    assert "免费额度" in body["error"]["message"]
