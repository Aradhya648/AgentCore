"""Per-model platform credential overrides (运营中转「一 key 一模型」, 成本配额与计费 §〇·六 F3).

The platform catalog may list several models; each may carry its own api_key / base_url
(``PLATFORM_MODEL_CREDENTIALS``). ``platform_llm_credentials(model=…)`` is the single point
that resolves「which upstream key + base_url serves this model」, falling back to the shared
``platform_api_key`` / ``platform_base_url`` for any missing field or unlisted model.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcore.billing.gate import preflight_llm_credentials
from agentcore.billing.preference import is_platform_available
from agentcore.config import settings
from agentcore.config.platform import parse_platform_model_credentials
from agentcore.core.errors import PlatformBillingUnavailableError
from agentcore.llm.resolve import (
    ModelSelection,
    platform_llm_credentials,
    resolve_model_config,
)

_OVERRIDE = (
    '{"grok-4.5": {"api_key": "sk-grok-key", "base_url": "https://relay.example/openai/v1"}}'
)


def _user():
    """A quota-bearing user (all override columns None → inherit deployment defaults)."""
    return SimpleNamespace(
        user_id="u1",
        is_unlimited=False,
        quota_daily_tokens=None,
        quota_monthly_cost_usd=None,
        quota_daily_cost_usd=None,
        quota_daily_requests=None,
    )


# --- parse_platform_model_credentials ----------------------------------------


def test_parse_valid_json_keeps_only_nonblank_fields():
    parsed = parse_platform_model_credentials(
        '{"a": {"api_key": "k1", "base_url": "u1"},'
        ' "b": {"api_key": "k2"},'
        ' "c": {"base_url": "u3"},'
        ' "d": {"api_key": "", "base_url": "  "},'
        ' "  ": {"api_key": "x"},'
        ' "e": "not-an-object"}'
    )
    assert parsed == {
        "a": {"api_key": "k1", "base_url": "u1"},
        "b": {"api_key": "k2"},
        "c": {"base_url": "u3"},
    }


def test_parse_blank_and_malformed_degrade_to_empty():
    assert parse_platform_model_credentials("") == {}
    assert parse_platform_model_credentials("   ") == {}
    assert parse_platform_model_credentials("{not json}") == {}
    assert parse_platform_model_credentials('["list", "not", "object"]') == {}


# --- platform_llm_credentials(model=…) ---------------------------------------


def test_no_arg_call_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(settings, "platform_model", "5.2")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    creds = platform_llm_credentials()
    assert creds is not None
    assert creds.api_key == "sk-default"
    assert creds.base_url == "https://default/v1"
    assert creds.default_model == "5.2"
    assert creds.source == "platform"


def test_override_model_uses_its_own_key_and_base_url(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(settings, "platform_model", "5.2")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    creds = platform_llm_credentials(model="grok-4.5")
    assert creds is not None
    assert creds.api_key == "sk-grok-key"
    assert creds.base_url == "https://relay.example/openai/v1"
    # default_model is the requested model, not settings.platform_model.
    assert creds.default_model == "grok-4.5"
    assert creds.source == "platform"


def test_unlisted_model_falls_back_to_default_key(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(settings, "platform_model", "5.2")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    creds = platform_llm_credentials(model="5.2")
    assert creds is not None
    # 5.2 has no override entry → shared default key/base_url, default_model=5.2.
    assert creds.api_key == "sk-default"
    assert creds.base_url == "https://default/v1"
    assert creds.default_model == "5.2"


def test_override_missing_base_url_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(
        settings, "platform_model_credentials", '{"m": {"api_key": "sk-m"}}'
    )
    creds = platform_llm_credentials(model="m")
    assert creds is not None
    assert creds.api_key == "sk-m"  # override key
    assert creds.base_url == "https://default/v1"  # base_url falls back


def test_override_only_key_serves_model_when_default_absent(monkeypatch):
    """No shared default key, but the model's override has one → resolvable."""
    monkeypatch.setattr(settings, "platform_api_key", "")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    assert platform_llm_credentials(model="grok-4.5") is not None
    # A model with neither an override key nor a default key stays None.
    assert platform_llm_credentials(model="5.2") is None
    assert platform_llm_credentials() is None


# --- is_platform_available ---------------------------------------------------


def test_is_platform_available_default_key(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    assert is_platform_available() is True


def test_is_platform_available_override_only_key(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    assert is_platform_available() is True


def test_is_platform_available_none(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "")
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    assert is_platform_available() is False
    # An override that carries only a base_url (no key) is not "available".
    monkeypatch.setattr(
        settings, "platform_model_credentials", '{"m": {"base_url": "https://x/v1"}}'
    )
    assert is_platform_available() is False


# --- gate 503 honors override-only availability -------------------------------


@pytest.mark.asyncio
async def test_gate_platform_unavailable_when_no_key_anywhere(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "")
    monkeypatch.setattr(settings, "platform_model_credentials", "")
    with pytest.raises(PlatformBillingUnavailableError):
        await preflight_llm_credentials(
            session=MagicMock(),
            user=SimpleNamespace(user_id="u1"),
            cost_repo=MagicMock(),
            byok_missing_message="missing",
            model_origin="platform",
        )


@pytest.mark.asyncio
async def test_gate_platform_available_via_override_key(monkeypatch):
    """Default key empty but an override carries a key → gate proceeds to quota (no 503)."""
    monkeypatch.setattr(settings, "platform_api_key", "")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    monkeypatch.setattr(settings, "billing_mode", "platform")
    with (
        patch("agentcore.billing.gate.user_has_provider", AsyncMock(return_value=False)),
        patch("agentcore.billing.gate.enforce_quota", AsyncMock()) as enforce,
    ):
        result = await preflight_llm_credentials(
            session=MagicMock(),
            user=_user(),
            cost_repo=MagicMock(),
            byok_missing_message="missing",
            model_origin="platform",
        )
    assert result is None  # platform path (per-model creds resolved at the call site)
    enforce.assert_awaited_once()


# --- resolve_model_config platform branch resolves per-model -----------------


def _mock_keyless(monkeypatch):
    """A keyless account: no BYOK provider → resolve falls to the platform key."""
    monkeypatch.setattr(
        "agentcore.db.repositories.UserRepository",
        lambda _s: SimpleNamespace(
            get_by_id=AsyncMock(
                return_value=SimpleNamespace(user_id="u1", default_chat_provider_id=None)
            )
        ),
    )
    monkeypatch.setattr(
        "agentcore.db.repositories.UserLlmProviderRepository",
        lambda _s: SimpleNamespace(
            get=AsyncMock(return_value=None),
            first_for_user=AsyncMock(return_value=None),
            count_for_user=AsyncMock(return_value=0),
        ),
    )
    # Account default is now profile-expand (not users.default_chat_*); stub the
    # selection so MagicMock sessions don't enter LlmModelProfileService → DB.
    monkeypatch.setattr(
        "agentcore.llm.resolve.resolve_account_default_model",
        AsyncMock(
            return_value=ModelSelection(
                model="grok-4.5", origin="platform", provider_id=None
            )
        ),
    )


@pytest.mark.asyncio
async def test_resolve_model_config_platform_chat_uses_per_model_key(monkeypatch):
    monkeypatch.setattr(settings, "platform_api_key", "")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(settings, "platform_model", "grok-4.5")
    monkeypatch.setattr(settings, "platform_background_model", "")
    monkeypatch.setattr(settings, "billing_mode", "platform")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    _mock_keyless(monkeypatch)
    cfg = await resolve_model_config(MagicMock(), "u1", "chat")
    assert cfg is not None
    assert cfg.source == "platform"
    assert cfg.model == "grok-4.5"
    assert cfg.api_key == "sk-grok-key"
    assert cfg.base_url == "https://relay.example/openai/v1"


@pytest.mark.asyncio
async def test_resolve_model_config_platform_background_downgrade_resolves_that_model(
    monkeypatch,
):
    """Background purpose 降档 to platform_background_model → its per-model key is used."""
    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(settings, "platform_model", "5.2")
    monkeypatch.setattr(settings, "platform_background_model", "grok-4.5")
    monkeypatch.setattr(settings, "billing_mode", "platform")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)
    _mock_keyless(monkeypatch)
    cfg = await resolve_model_config(MagicMock(), "u1", "title")
    assert cfg is not None
    assert cfg.source == "platform"
    assert cfg.model == "grok-4.5"  # downgraded model name
    assert cfg.api_key == "sk-grok-key"  # resolved for the downgraded model


# --- PlatformProvider: per-request model → key (辩论跨模型 / F3) --------------


@pytest.mark.asyncio
async def test_platform_provider_uses_per_model_key(monkeypatch):
    """同一 leaf 上 5.2 与 grok-4.5 必须打到各自的 key（回归：冻死 grok key → 5.2 403）。"""
    from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
    from agentcore.llm.provider.platform import PlatformProvider
    from agentcore.llm.provider.protocol import LLMMessage, LLMRequest, LLMResponse

    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(settings, "platform_model", "5.2")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)

    seen: list[tuple[str, str]] = []

    async def _capture_complete(self, request):  # noqa: ANN001
        seen.append((request.model, self._api_key))
        return LLMResponse(content="ok", model=request.model)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", _capture_complete)
    provider = PlatformProvider()
    msgs = [LLMMessage(role="user", content="hi")]
    await provider.complete(LLMRequest(messages=msgs, model="5.2"))
    await provider.complete(LLMRequest(messages=msgs, model="grok-4.5"))
    assert seen == [("5.2", "sk-default"), ("grok-4.5", "sk-grok-key")]
    await provider.close()


@pytest.mark.asyncio
async def test_build_provider_platform_source_is_resolving_leaf(monkeypatch):
    from agentcore.llm.call_fence import unwrap_provider
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.factory import build_provider
    from agentcore.llm.provider.platform import PlatformProvider

    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    provider = build_provider(
        LLMCredentials(
            api_key="sk-ignored-frozen",
            base_url="https://ignored/v1",
            default_model="5.2",
            source="platform",
        )
    )
    assert isinstance(unwrap_provider(provider), PlatformProvider)


@pytest.mark.asyncio
async def test_ensure_debate_route_extras_platform_per_model(monkeypatch):
    """正方 5.2 + 反方 grok-4.5：router ``platform/…`` 各自用对 key。"""
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.factory import build_router
    from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
    from agentcore.llm.provider.protocol import LLMMessage, LLMRequest, LLMResponse
    from agentcore.runtime.debate.models import ModelIdentity, ensure_debate_route_extras

    monkeypatch.setattr(settings, "platform_api_key", "sk-default")
    monkeypatch.setattr(settings, "platform_base_url", "https://default/v1")
    monkeypatch.setattr(settings, "platform_model", "5.2")
    monkeypatch.setattr(settings, "platform_model_credentials", _OVERRIDE)

    seen: list[tuple[str, str]] = []

    async def _capture_complete(self, request):  # noqa: ANN001
        seen.append((request.model, self._api_key))
        return LLMResponse(content="ok", model=request.model)

    monkeypatch.setattr(OpenAICompatibleProvider, "complete", _capture_complete)

    # Turn main is BYOK — debate must inject platform extras (the production shape).
    router = build_router(
        LLMCredentials(
            api_key="sk-byok",
            base_url="https://byok.example/v1",
            default_model="deepseek-v4-flash",
            source="user",
            provider_id="prov-ds",
        )
    )
    await ensure_debate_route_extras(
        router,
        [
            ModelIdentity(model="5.2", origin="platform"),
            ModelIdentity(model="grok-4.5", origin="platform"),
        ],
    )
    assert "platform" in router.available_prefixes
    msgs = [LLMMessage(role="user", content="hi")]
    await router.complete(LLMRequest(messages=msgs, model="platform/5.2"))
    await router.complete(LLMRequest(messages=msgs, model="platform/grok-4.5"))
    assert seen == [("5.2", "sk-default"), ("grok-4.5", "sk-grok-key")]
    await router.close()
