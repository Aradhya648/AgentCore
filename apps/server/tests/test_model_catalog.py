"""Model catalog + 会话级模型切换 (multi-BYOK-provider + platform catalog)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

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


def _prov(pid: str, *, default_model: str = "deepseek-v4-flash", label: str = "P"):
    return SimpleNamespace(
        id=pid,
        user_id="u1",
        label=label,
        default_model=default_model,
        base_url=f"http://{pid}/v1",
        api_key_enc=b"x",
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


async def test_catalog_dormant_hides_platform_despite_key(monkeypatch):
    """byok + free_tier off + PLATFORM_API_KEY still set → no platform catalog rows."""
    reset_discovery_cache_for_tests()
    row = _prov("provA", label="DeepSeek")
    monkeypatch.setattr(catalog.settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(catalog.settings, "billing_mode", "byok")
    monkeypatch.setattr(catalog.settings, "platform_free_tier_enabled", False)
    monkeypatch.setattr(catalog.settings, "platform_model", "deepseek-v4-flash")
    monkeypatch.setattr(catalog.settings, "platform_models", "5.2,grok-4.5")
    _mock_catalog(
        monkeypatch,
        providers=[row],
        selection=ModelSelection(model="deepseek-v4-flash", origin="byok", provider_id="provA"),
        discovered={"provA": ["deepseek-v4-flash"]},
    )
    cat = await resolve_model_catalog(None, "u1")
    assert all(m.origin == "byok" for m in cat.models)
    assert not any(m.origin == "platform" for m in cat.models)


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
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="sys",
        name="5.2",
        kind="system",
        main=ModelSelection(model="deepseek-v4-pro", origin="platform", provider_id=None),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=expanded),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )
    conv = SimpleNamespace(model_profile_id="sys")

    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "deepseek-v4-pro"
    assert sel.origin == "platform"
    assert sel.provider_id is None

    profiles = await resolve_turn_profiles(None, conv, "u1", credentials=None)
    assert profiles.model == "deepseek-v4-pro"


async def test_resolve_turn_profiles_no_worker_slot_follows_main(monkeypatch):
    """worker 空槽 → model_overrides 无 agent；CEO/worker 同 model。"""
    from agentcore.conversation.common import resolve_turn_profiles
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="p",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="main-model", origin="byok", provider_id="p1"),
        worker=None,
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=expanded),
    )
    conv = SimpleNamespace(model_profile_id="p")
    creds = LLMCredentials(api_key="sk", base_url="https://x", default_model="main-model")
    profiles = await resolve_turn_profiles(None, conv, "u1", credentials=creds)
    assert profiles.model == "main-model"
    assert "agent" not in profiles.model_overrides
    assert profiles.model_for("agent") == "main-model"
    assert profiles.agent_provider_id is None


async def test_resolve_turn_profiles_worker_slot_overrides_agent(monkeypatch):
    """配了 worker 槽 → model_for(agent)=worker；model_for(chat) 仍为主模型。"""
    from agentcore.conversation.common import resolve_turn_profiles
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="p",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="ceo-pro", origin="byok", provider_id="p1"),
        worker=ModelSelection(model="worker-flash", origin="byok", provider_id="p2"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=expanded),
    )
    conv = SimpleNamespace(model_profile_id="p")
    creds = LLMCredentials(api_key="sk", base_url="https://x", default_model="ceo-pro")
    profiles = await resolve_turn_profiles(None, conv, "u1", credentials=creds)
    assert profiles.model == "ceo-pro"
    assert profiles.model_for("chat") == "ceo-pro"
    assert profiles.model_for("agent") == "worker-flash"
    assert profiles.agent_provider_id == "p2"
    assert profiles.route_model_for("agent") == "p2/worker-flash"


async def test_resolve_turn_profiles_worker_platform_with_byok_main(monkeypatch):
    """主 byok、worker platform → agent_provider_id=platform 哨兵。"""
    from agentcore.conversation.common import resolve_turn_profiles
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.profiles import PLATFORM_PROVIDER_SENTINEL
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="p",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="ceo-pro", origin="byok", provider_id="p1"),
        worker=ModelSelection(
            model="deepseek-v4-flash", origin="platform", provider_id=None
        ),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=expanded),
    )
    conv = SimpleNamespace(model_profile_id="p")
    creds = LLMCredentials(
        api_key="sk", base_url="https://x", default_model="ceo-pro", provider_id="p1"
    )
    profiles = await resolve_turn_profiles(None, conv, "u1", credentials=creds)
    assert profiles.model_for("agent") == "deepseek-v4-flash"
    assert profiles.agent_provider_id == PLATFORM_PROVIDER_SENTINEL
    assert profiles.route_model_for("agent", turn_provider_id="p1") == (
        f"{PLATFORM_PROVIDER_SENTINEL}/deepseek-v4-flash"
    )


async def test_resolve_account_default_from_profile(monkeypatch):
    """账号默认组合展开为主槽。"""
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection, resolve_account_default_model

    expanded = ExpandedProfile(
        profile_id="p",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="deepseek-v4-pro", origin="platform", provider_id=None),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )
    sel = await resolve_account_default_model(None, "u1")
    assert sel.origin == "platform"
    assert sel.provider_id is None
    assert sel.model == "deepseek-v4-pro"


async def test_resolve_turn_profiles_dangling_worker_follows_main(monkeypatch):
    """worker 槽展开为 None（删服务商后）→ 跟随主模型。"""
    from agentcore.conversation.common import resolve_turn_profiles
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="p",
        name="当前配置",
        kind="user",
        main=ModelSelection(model="ceo-pro", origin="byok", provider_id="p1"),
        worker=None,
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=expanded),
    )
    conv = SimpleNamespace(model_profile_id="p")
    creds = LLMCredentials(api_key="sk", base_url="https://x", default_model="ceo-pro")
    profiles = await resolve_turn_profiles(None, conv, "u1", credentials=creds)
    assert profiles.model_for("agent") == "ceo-pro"
    assert "agent" not in profiles.model_overrides


async def test_conversation_profile_pin_expands_main(monkeypatch):
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    expanded = ExpandedProfile(
        profile_id="imp",
        name="会话覆盖",
        kind="implicit",
        main=ModelSelection(model="picked", origin="byok", provider_id="p1"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=expanded),
    )
    conv = SimpleNamespace(model_profile_id="imp")
    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "picked"
    assert sel.origin == "byok"
    assert sel.provider_id == "p1"


async def test_dangling_profile_falls_back_via_expand(monkeypatch):
    """展开侧对悬空 pin 回落到账号/系统默认。"""
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    fallback = ExpandedProfile(
        profile_id="bal",
        name="5.2",
        kind="system",
        main=ModelSelection(model="acct-model", origin="byok", provider_id="p2"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=fallback),
    )
    conv = SimpleNamespace(model_profile_id="dead")
    sel = await resolve_conversation_model_selection(None, conv, "u1")
    assert sel.model == "acct-model"
    assert sel.provider_id == "p2"


# --- conversation PATCH (crud) -----------------------------------------------


async def test_patch_conversation_persists_model_profile_id(monkeypatch):
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
        model_profile_id=None,
    )

    class _Repo:
        _session = None

        async def get_by_id(self, _cid, *, user_id):
            return conv

        async def set_model_profile(self, _cid, model_profile_id, *, user_id):
            written["model_profile_id"] = model_profile_id
            conv.model_profile_id = model_profile_id
            return conv

    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.ensure_profile_usable",
        AsyncMock(return_value=None),
    )
    body = UpdateConversationRequest(model_profile_id="prof-1")
    result = await crud.update_conversation(
        "c1", body, SimpleNamespace(user_id="u1"), repo=_Repo()
    )
    assert written == {"model_profile_id": "prof-1"}
    assert result.model_profile_id == "prof-1"


async def test_patch_conversation_clears_model_profile_id(monkeypatch):
    from datetime import datetime

    from agentcore.api.routes.conversations import crud
    from agentcore.api.schemas import UpdateConversationRequest

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
        model_profile_id="prof-1",
    )

    class _Repo:
        _session = None

        async def get_by_id(self, _cid, *, user_id):
            return conv

        async def set_model_profile(self, _cid, model_profile_id, *, user_id):
            conv.model_profile_id = model_profile_id
            return conv

    body = UpdateConversationRequest(model_profile_id=None)
    # Explicit null is in model_fields_set.
    assert "model_profile_id" in body.model_fields_set
    result = await crud.update_conversation(
        "c1", body, SimpleNamespace(user_id="u1"), repo=_Repo()
    )
    assert result.model_profile_id is None


# --- inference proxy authoritative re-resolution ------------------------------


async def test_inference_proxy_uses_conversation_profile(monkeypatch):
    from agentcore.api.routes import inference
    from agentcore.llm.model_profiles import ExpandedProfile
    from agentcore.llm.resolve import ModelSelection

    creds = LLMCredentials(
        api_key="sk", base_url="https://api.deepseek.com", default_model="account-model"
    )
    seen: dict = {}

    async def _fake_preflight(**kw):
        seen["origin"] = kw["model_origin"]
        seen["provider_id"] = kw["provider_id"]
        return creds

    monkeypatch.setattr(inference.proxy, "preflight_llm_credentials", _fake_preflight)
    expanded = ExpandedProfile(
        profile_id="imp",
        name="会话",
        kind="implicit",
        main=ModelSelection(model="picked-model", origin="byok", provider_id="p1"),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand_for_conversation",
        AsyncMock(return_value=expanded),
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.LlmModelProfileService.expand",
        AsyncMock(return_value=expanded),
    )

    class _ConvRepo:
        def __init__(self, _session):
            pass

        async def get_by_id(self, cid, *, user_id):
            return SimpleNamespace(id=cid, model_profile_id="imp")

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
