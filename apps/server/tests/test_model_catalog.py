"""Model catalog + 会话级模型切换 (multi-BYOK-provider + platform catalog)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from agentcore.core.errors import ValidationError
from agentcore.llm import catalog
from agentcore.llm.catalog import (
    reset_discovery_cache_for_tests,
    resolve_model_catalog,
    validate_model_choice,
)
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.llm.resolve import (
    ModelSelection,
    resolve_conversation_model_selection,
    resolve_turn_model,
)

pytestmark = pytest.mark.anyio


# --- helpers -----------------------------------------------------------------


def _prov(pid: str, *, default_model: str = "deepseek-v4-flash", label: str = "P", price=None):
    price = price or {}
    return SimpleNamespace(
        id=pid,
        user_id="u1",
        label=label,
        default_model=default_model,
        base_url=f"http://{pid}/v1",
        api_key_enc=b"x",
        price_cache_hit=price.get("cache_hit"),
        price_cache_miss=price.get("cache_miss"),
        price_output=price.get("output"),
        supports_tools=None,
        status="active",
    )


def _creds(row) -> LLMCredentials:
    return LLMCredentials(
        api_key="k",
        base_url=row.base_url,
        default_model=row.default_model,
        source="user",
        provider_id=row.id,
    )


def _mock_catalog(monkeypatch, *, providers, selection, discovered=None):
    """Patch the catalog's provider list / decrypt / discovery / account default."""
    monkeypatch.setattr(catalog, "list_user_providers", AsyncMock(return_value=providers))
    monkeypatch.setattr(catalog, "resolve_account_default_model", AsyncMock(return_value=selection))
    monkeypatch.setattr(catalog, "_decrypt_provider", lambda row, _uid: _creds(row))
    discovered = discovered or {}

    async def _disc(row, _creds):
        return discovered.get(row.id)

    monkeypatch.setattr(catalog, "_discover_provider_models", _disc)


# --- resolve_turn_model priority (unchanged skeleton) -------------------------


def test_resolve_turn_model_conversation_override_wins():
    creds = LLMCredentials(api_key="k", base_url="u", default_model="account-model")
    assert resolve_turn_model(creds, conversation_model="picked-model") == "picked-model"


def test_resolve_turn_model_blank_override_falls_back_to_default_model():
    creds = LLMCredentials(api_key="k", base_url="u", default_model="account-model")
    assert resolve_turn_model(creds, conversation_model=None) == "account-model"
    assert resolve_turn_model(creds, conversation_model="   ") == "account-model"


# --- provider GET /models discovery ------------------------------------------


def _mock_transport_provider(handler) -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider(name="test", api_key="k", base_url="http://up/v1")
    provider._client = httpx.AsyncClient(
        base_url="http://up/v1", transport=httpx.MockTransport(handler)
    )
    return provider


async def test_list_models_parses_dedupes_and_drops_blanks():
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={"data": [{"id": "m1"}, {"id": "m2"}, {"id": ""}, {"id": "m1"}, {"no": "id"}]},
        )

    ids = await _mock_transport_provider(_handler).list_models()
    assert ids == ["m1", "m2"]


def _fake_provider(*, ids: list[str] | None = None, error: Exception | None = None):
    class _Provider:
        async def list_models(self):
            if error is not None:
                raise error
            return list(ids or [])

        async def close(self):
            return None

    return _Provider()


async def test_discovery_caches_within_ttl_per_provider(monkeypatch):
    reset_discovery_cache_for_tests()
    row = _prov("prov-1")
    creds = _creds(row)
    calls = {"n": 0}

    def _build(_creds):
        calls["n"] += 1
        return _fake_provider(ids=["a", "b"])

    monkeypatch.setattr("agentcore.llm.factory.build_provider", _build)
    first = await catalog._discover_provider_models(row, creds)
    second = await catalog._discover_provider_models(row, creds)
    assert first == ["a", "b"]
    assert second == ["a", "b"]
    assert calls["n"] == 1  # cached by (provider_id, base_url)


# --- unified catalog ----------------------------------------------------------


async def test_catalog_with_key_mixes_byok_and_platform(monkeypatch):
    reset_discovery_cache_for_tests()
    row = _prov("prov-1", default_model="deepseek-v4-flash", label="DeepSeek")
    monkeypatch.setattr(catalog.settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(catalog.settings, "billing_mode", "platform")
    monkeypatch.setattr(catalog.settings, "platform_model", "deepseek-v4-flash")
    monkeypatch.setattr(catalog.settings, "platform_models", "")
    _mock_catalog(
        monkeypatch,
        providers=[row],
        selection=ModelSelection(model="deepseek-v4-flash", origin="byok", provider_id="prov-1"),
        discovered={"prov-1": ["deepseek-v4-flash", "some-endpoint-model"]},
    )
    cat = await resolve_model_catalog(None, "u1")
    assert cat.byok_configured is True
    assert cat.current.id == "deepseek-v4-flash"
    assert cat.current.origin == "byok"
    assert cat.current.provider_id == "prov-1"
    keys = {(m.id, m.origin, m.provider_id) for m in cat.models}
    assert ("deepseek-v4-flash", "byok", "prov-1") in keys
    assert ("deepseek-v4-flash", "platform", None) in keys
    assert ("some-endpoint-model", "byok", "prov-1") in keys
    # BYOK rows carry the provider label for UI grouping.
    byok = [m for m in cat.models if m.origin == "byok"]
    assert all(m.available and m.provider_label == "DeepSeek" for m in byok)


async def test_catalog_same_model_id_under_two_providers(monkeypatch):
    """同一模型 id 允许同时出现在多个服务商下 — (id, origin, provider_id) is the key."""
    reset_discovery_cache_for_tests()
    a = _prov("provA", label="Ark")
    b = _prov("provB", label="Kimi")
    monkeypatch.setattr(catalog.settings, "platform_api_key", "")
    monkeypatch.setattr(catalog.settings, "billing_mode", "byok")
    _mock_catalog(
        monkeypatch,
        providers=[a, b],
        selection=ModelSelection(model="deepseek-v4-flash", origin="byok", provider_id="provA"),
        discovered={"provA": ["shared-model"], "provB": ["shared-model"]},
    )
    cat = await resolve_model_catalog(None, "u1")
    keys = {(m.id, m.origin, m.provider_id) for m in cat.models}
    assert ("shared-model", "byok", "provA") in keys
    assert ("shared-model", "byok", "provB") in keys
    shared = [m for m in cat.models if m.id == "shared-model"]
    assert {m.provider_label for m in shared} == {"Ark", "Kimi"}


async def test_catalog_keyless_platform_on_hides_guide_rows(monkeypatch):
    monkeypatch.setattr(catalog.settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(catalog.settings, "billing_mode", "platform")
    monkeypatch.setattr(catalog.settings, "platform_model", "deepseek-v4-flash")
    monkeypatch.setattr(catalog.settings, "platform_models", "")
    _mock_catalog(
        monkeypatch,
        providers=[],
        selection=ModelSelection(model="deepseek-v4-flash", origin="platform", provider_id=None),
    )
    cat = await resolve_model_catalog(None, "u1")
    assert cat.byok_configured is False
    assert cat.current.origin == "platform"
    keys = {(m.id, m.origin) for m in cat.models}
    assert ("deepseek-v4-flash", "platform") in keys
    assert all(m.origin == "platform" and m.available for m in cat.models)


async def test_catalog_keyless_platform_off_returns_empty(monkeypatch):
    """Keyless + no platform subsidy: empty catalog (UI shows an empty state, no guide rows)."""
    monkeypatch.setattr(catalog.settings, "platform_api_key", "")
    monkeypatch.setattr(catalog.settings, "billing_mode", "byok")
    monkeypatch.setattr(catalog.settings, "platform_free_tier_enabled", False)
    _mock_catalog(
        monkeypatch,
        providers=[],
        selection=ModelSelection(model="deepseek-v4-flash", origin="byok", provider_id=None),
    )
    cat = await resolve_model_catalog(None, "u1")
    assert cat.byok_configured is False
    assert cat.models == []


async def test_catalog_platform_allowlist_drives_rows(monkeypatch):
    monkeypatch.setattr(catalog.settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(catalog.settings, "billing_mode", "platform")
    monkeypatch.setattr(catalog.settings, "platform_model", "deepseek-v4-flash")
    monkeypatch.setattr(
        catalog.settings,
        "platform_models",
        "deepseek-v4-flash, deepseek-v4-pro , gpt-4o, deepseek-v4-pro",
    )
    _mock_catalog(
        monkeypatch,
        providers=[],
        selection=ModelSelection(model="deepseek-v4-flash", origin="platform", provider_id=None),
    )
    cat = await resolve_model_catalog(None, "u1")
    platform_ids = [m.id for m in cat.models if m.origin == "platform"]
    assert platform_ids == ["deepseek-v4-flash", "deepseek-v4-pro", "gpt-4o"]
    assert all(m.available and m.price is not None for m in cat.models if m.origin == "platform")


# --- validate_model_choice ----------------------------------------------------


async def test_validate_platform_allowlist_membership(monkeypatch):
    monkeypatch.setattr(catalog.settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(catalog.settings, "billing_mode", "platform")
    monkeypatch.setattr(catalog.settings, "platform_models", "deepseek-v4-pro,gpt-4o")
    _mock_catalog(
        monkeypatch,
        providers=[],
        selection=ModelSelection(model="deepseek-v4-pro", origin="platform", provider_id=None),
    )
    assert await validate_model_choice(None, "u1", "gpt-4o", "platform") is True
    assert await validate_model_choice(None, "u1", "deepseek-v4-pro", "platform") is True
    assert await validate_model_choice(None, "u1", "deepseek-v4-flash", "platform") is False


async def test_validate_model_choice_is_provider_scoped(monkeypatch):
    """The same model id under a different provider is a different (invalid) choice."""
    reset_discovery_cache_for_tests()
    a = _prov("provA")
    b = _prov("provB")
    monkeypatch.setattr(catalog.settings, "platform_api_key", "")
    monkeypatch.setattr(catalog.settings, "billing_mode", "byok")
    _mock_catalog(
        monkeypatch,
        providers=[a, b],
        selection=ModelSelection(model="deepseek-v4-flash", origin="byok", provider_id="provA"),
        discovered={"provA": ["shared-model"], "provB": ["other-model"]},
    )
    assert await validate_model_choice(None, "u1", "shared-model", "byok", "provA") is True
    # shared-model is not under provB → rejected when that provider is specified.
    assert await validate_model_choice(None, "u1", "shared-model", "byok", "provB") is False
    # byok choice with no provider specified never matches a provider-tagged row.
    assert await validate_model_choice(None, "u1", "shared-model", "byok", None) is False


def test_has_curated_pricing_flags_uncurated():
    from agentcore.llm.pricing import has_curated_pricing

    assert has_curated_pricing("deepseek-v4-flash")
    assert has_curated_pricing("gpt-4o")
    assert not has_curated_pricing("totally-unknown-relay-model")


# --- resolve_conversation_model_selection ------------------------------------


def _mock_resolve_repos(monkeypatch, *, user=None, provider_by_id=None, first=None, count=0):
    provider_by_id = provider_by_id or {}
    monkeypatch.setattr(
        "agentcore.db.repositories.UserRepository",
        lambda _s: SimpleNamespace(get_by_id=AsyncMock(return_value=user)),
    )

    async def _get(pid, *, user_id):
        return provider_by_id.get(pid)

    monkeypatch.setattr(
        "agentcore.db.repositories.UserLlmProviderRepository",
        lambda _s: SimpleNamespace(
            get=_get,
            first_for_user=AsyncMock(return_value=first),
            count_for_user=AsyncMock(return_value=count),
        ),
    )


async def test_platform_selection_passes_through_to_turn(monkeypatch):
    from agentcore.conversation.common import resolve_turn_profiles

    monkeypatch.setattr("agentcore.llm.resolve.settings.billing_mode", "platform")
    monkeypatch.setattr("agentcore.llm.resolve.settings.platform_model", "deepseek-v4-flash")
    monkeypatch.setattr("agentcore.llm.resolve.settings.platform_api_key", "sk-platform")
    _mock_resolve_repos(monkeypatch, user=None, count=0)
    conv = SimpleNamespace(model="deepseek-v4-pro", model_origin="platform", model_provider_id=None)

    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "deepseek-v4-pro"
    assert sel.origin == "platform"
    assert sel.provider_id is None

    profiles = await resolve_turn_profiles(None, conv, "u1", credentials=None)
    assert profiles.model == "deepseek-v4-pro"


async def test_byok_override_pins_live_provider(monkeypatch):
    row = _prov("p1")
    _mock_resolve_repos(monkeypatch, user=SimpleNamespace(user_id="u1"), provider_by_id={"p1": row})
    conv = SimpleNamespace(model="picked", model_origin="byok", model_provider_id="p1")
    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "picked"
    assert sel.origin == "byok"
    assert sel.provider_id == "p1"


async def test_byok_override_deleted_provider_falls_back(monkeypatch):
    """删除服务商后：pinned provider gone → silent full fallback to account default."""
    _mock_resolve_repos(monkeypatch, user=SimpleNamespace(user_id="u1"), provider_by_id={})
    monkeypatch.setattr(
        "agentcore.llm.resolve.resolve_account_default_model",
        AsyncMock(
            return_value=ModelSelection(model="acct-model", origin="byok", provider_id="p2")
        ),
    )
    conv = SimpleNamespace(model="pinned", model_origin="byok", model_provider_id="dead")
    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "acct-model"
    assert sel.provider_id == "p2"


async def test_legacy_conversation_null_provider_keeps_model_on_default(monkeypatch):
    """origin=byok, provider_id NULL (legacy) → keep model on the account default provider."""
    row = _prov("p1")
    _mock_resolve_repos(
        monkeypatch,
        user=SimpleNamespace(user_id="u1", default_chat_provider_id=None),
        first=row,
        count=1,
    )
    conv = SimpleNamespace(model="legacy-model", model_origin="byok", model_provider_id=None)
    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "legacy-model"
    assert sel.origin == "byok"
    assert sel.provider_id == "p1"


async def test_legacy_conversation_origin_none_with_provider(monkeypatch):
    row = _prov("p1")
    _mock_resolve_repos(
        monkeypatch,
        user=SimpleNamespace(user_id="u1", default_chat_provider_id=None),
        first=row,
        count=1,
    )
    conv = SimpleNamespace(model="legacy-model", model_origin=None, model_provider_id=None)
    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "legacy-model"
    assert sel.origin == "byok"
    assert sel.provider_id == "p1"


async def test_legacy_conversation_byok_without_key_falls_back(monkeypatch):
    monkeypatch.setattr("agentcore.llm.resolve.settings.platform_model", "plat")
    monkeypatch.setattr("agentcore.llm.resolve.settings.billing_mode", "platform")
    _mock_resolve_repos(monkeypatch, user=SimpleNamespace(user_id="u1"), count=0)
    conv = SimpleNamespace(model="stale-byok", model_origin="byok", model_provider_id=None)
    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "plat"
    assert sel.origin == "platform"


# --- conversation PATCH (crud) -----------------------------------------------


async def test_patch_conversation_requires_origin(monkeypatch):
    from agentcore.api.routes.conversations import crud
    from agentcore.api.schemas import UpdateConversationRequest

    conv = SimpleNamespace(id="c1", model=None, model_origin=None, model_provider_id=None)

    class _Repo:
        _session = None

        async def get_by_id(self, _cid, *, user_id):
            return conv

    body = UpdateConversationRequest(model="deepseek-v4-flash")
    with pytest.raises(ValidationError):
        await crud.update_conversation(
            "c1", body, SimpleNamespace(user_id="u1"), repo=_Repo()
        )


async def test_patch_conversation_persists_model_origin_and_provider(monkeypatch):
    from datetime import datetime

    from agentcore.api.routes.conversations import crud
    from agentcore.api.schemas import UpdateConversationRequest

    written: dict = {}
    conv = SimpleNamespace(
        id="c1",
        title="t",
        updated_at=datetime.now(),
        created_at=datetime.now(),
        message_count=0,
        folder_id=None,
        local_container_root_id=None,
        pinned=False,
        archived=False,
        permission_preset="workspace",
        deep_research_auto=False,
        model=None,
        model_origin=None,
        model_provider_id=None,
    )

    class _Repo:
        _session = None

        async def get_by_id(self, _cid, *, user_id):
            return conv

        async def set_model(self, _cid, model, *, user_id, model_origin, model_provider_id):
            written["model"] = model
            written["model_origin"] = model_origin
            written["model_provider_id"] = model_provider_id
            conv.model = model
            conv.model_origin = model_origin
            conv.model_provider_id = model_provider_id
            return conv

    monkeypatch.setattr(
        "agentcore.llm.catalog.validate_model_choice", AsyncMock(return_value=True)
    )
    body = UpdateConversationRequest(
        model="shared-model", model_origin="byok", model_provider_id="p1"
    )
    result = await crud.update_conversation(
        "c1", body, SimpleNamespace(user_id="u1"), repo=_Repo()
    )
    assert written == {"model": "shared-model", "model_origin": "byok", "model_provider_id": "p1"}
    assert result.model == "shared-model"
    assert result.model_provider_id == "p1"


# --- inference proxy authoritative re-resolution ------------------------------


async def test_inference_proxy_uses_conversation_provider(monkeypatch):
    from agentcore.api.routes import inference

    creds = LLMCredentials(
        api_key="sk", base_url="https://api.deepseek.com", default_model="account-model"
    )
    seen: dict = {}

    async def _fake_preflight(**kw):
        seen["origin"] = kw["model_origin"]
        seen["provider_id"] = kw["provider_id"]
        return creds

    monkeypatch.setattr(inference.proxy, "preflight_llm_credentials", _fake_preflight)
    row = _prov("p1")
    _mock_resolve_repos(monkeypatch, user=SimpleNamespace(user_id="u1"), provider_by_id={"p1": row})

    class _ConvRepo:
        def __init__(self, _session):
            pass

        async def get_by_id(self, cid, *, user_id):
            return SimpleNamespace(
                id=cid, model="picked-model", model_origin="byok", model_provider_id="p1"
            )

    monkeypatch.setattr("agentcore.db.repositories.ConversationRepository", _ConvRepo)
    cfg = await inference._resolve_inference_credentials(
        None,
        None,
        SimpleNamespace(user_id="u1"),
        conversation_id="c1",
    )
    assert seen["origin"] == "byok"
    assert seen["provider_id"] == "p1"
    assert cfg.model == "picked-model"
    assert cfg.source == "byok"
