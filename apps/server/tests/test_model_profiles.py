"""Unit tests for dynamic platform system presets (uuid5 projection)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.llm.model_profiles import (
    LlmModelProfileService,
    is_system_profile_id,
    platform_preset_id,
    resolve_system_preset_main,
    system_presets,
    system_profile_default_id,
)

# Former hardcoded product UUIDs — must NOT be recognized as system presets.
_LEGACY_SYSTEM_PROFILE_52 = "00000000-0000-4000-8000-000000000011"
_LEGACY_SYSTEM_PROFILE_GROK = "00000000-0000-4000-8000-000000000012"


def _glm_preset_id() -> str:
    return platform_preset_id("glm-5.2")


def test_platform_preset_id_is_stable_uuid5():
    expected = str(
        uuid.uuid5(uuid.NAMESPACE_URL, "agentcore:platform-preset:glm-5.2")
    )
    assert platform_preset_id("glm-5.2") == expected
    assert platform_preset_id("glm-5.2") == platform_preset_id("glm-5.2")
    assert platform_preset_id("glm-5.2") != platform_preset_id("grok-4.5")


def test_system_presets_project_from_listable_catalog(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2", "grok-4.5"],
    )
    presets = system_presets()
    assert list(presets.values()) == ["glm-5.2", "grok-4.5"]
    assert presets[_glm_preset_id()] == "glm-5.2"
    assert presets[platform_preset_id("grok-4.5")] == "grok-4.5"
    assert is_system_profile_id(_glm_preset_id())
    assert not is_system_profile_id(_LEGACY_SYSTEM_PROFILE_52)
    assert not is_system_profile_id(_LEGACY_SYSTEM_PROFILE_GROK)
    assert not is_system_profile_id("00000000-0000-4000-8000-000000000002")


def test_system_profile_default_prefers_platform_model(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["grok-4.5", "glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.settings.platform_model",
        "glm-5.2",
    )
    assert system_profile_default_id() == _glm_preset_id()


def test_system_profile_default_falls_to_first_when_platform_model_absent(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["grok-4.5", "glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.settings.platform_model",
        "not-in-list",
    )
    assert system_profile_default_id() == platform_preset_id("grok-4.5")


def test_resolve_system_preset_main_is_fixed(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    sel = resolve_system_preset_main(_glm_preset_id())
    assert sel.model == "glm-5.2"
    assert sel.origin == "platform"
    assert sel.provider_id is None


@pytest.mark.asyncio
async def test_list_profiles_hides_missing_catalog_models(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: [],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[])  # type: ignore[method-assign]

    views = await svc.list_profiles("u1")
    assert views == []


@pytest.mark.asyncio
async def test_list_profiles_hides_system_when_platform_billing_off(monkeypatch):
    """byok + free-tier off: allowlist may still list glm-5.2 — presets must hide."""
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: False,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[])  # type: ignore[method-assign]

    views = await svc.list_profiles("u1")
    assert views == []


@pytest.mark.asyncio
async def test_list_profiles_marks_default_when_present(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.settings.platform_model",
        "glm-5.2",
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[])  # type: ignore[method-assign]

    views = await svc.list_profiles("u1")
    assert [v.id for v in views] == [_glm_preset_id()]
    assert views[0].is_default is True
    assert views[0].name == "GLM-5.2"
    assert views[0].main.model == "glm-5.2"
    assert views[0].worker is None
    assert views[0].background is None


@pytest.mark.asyncio
async def test_list_profiles_projects_multiple_models(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2", "grok-4.5"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.settings.platform_model",
        "glm-5.2",
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[])  # type: ignore[method-assign]

    views = await svc.list_profiles("u1")
    assert [v.main.model for v in views] == ["glm-5.2", "grok-4.5"]
    assert views[0].is_default is True
    assert views[1].name == "Grok 4.5"


@pytest.mark.asyncio
async def test_expand_none_and_dangling_fall_back_to_platform_default(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.settings.platform_model",
        "glm-5.2",
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.get = AsyncMock(return_value=None)  # type: ignore[method-assign]

    expanded = await svc.expand("u1", None)
    assert expanded.profile_id == _glm_preset_id()
    assert expanded.main.model == "glm-5.2"
    assert expanded.name == "GLM-5.2"

    dangling = await svc.expand("u1", "00000000-0000-4000-8000-000000000002")
    assert dangling.profile_id == _glm_preset_id()
    assert dangling.main.model == "glm-5.2"


@pytest.mark.asyncio
async def test_expand_legacy_hardcoded_uuid_falls_back_to_default(monkeypatch):
    """Old …0011 / …0012 ids are not system presets → dangling → PLATFORM_MODEL preset."""
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles.settings.platform_model",
        "glm-5.2",
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.get = AsyncMock(return_value=None)  # type: ignore[method-assign]

    for legacy in (_LEGACY_SYSTEM_PROFILE_52, _LEGACY_SYSTEM_PROFILE_GROK):
        expanded = await svc.expand("u1", legacy)
        assert expanded.profile_id == _glm_preset_id()
        assert expanded.main.model == "glm-5.2"


@pytest.mark.asyncio
async def test_set_default_rejects_unavailable_system_preset(monkeypatch):
    from agentcore.core.errors import ValidationError

    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: False,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    with pytest.raises(ValidationError, match="不可用"):
        await svc.set_default("u1", _glm_preset_id())


@pytest.mark.asyncio
async def test_ensure_rejects_unavailable_system_preset(monkeypatch):
    from agentcore.core.errors import ValidationError

    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: False,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    with pytest.raises(ValidationError, match="不可用"):
        await svc.ensure_profile_usable("u1", _glm_preset_id())


@pytest.mark.asyncio
async def test_list_marks_user_default_when_system_pin_dormant(monkeypatch):
    """DB pin on invisible system preset → list marks first visible user combo (no DB write)."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: False,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    user_row = SimpleNamespace(
        id="user-combo-1",
        name="我的组合",
        kind="user",
        main_origin="byok",
        main_model="gpt-4o",
        main_provider_id="p1",
        worker_origin=None,
        worker_model=None,
        worker_provider_id=None,
        background_origin=None,
        background_model=None,
        background_provider_id=None,
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=_glm_preset_id())  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[user_row])  # type: ignore[method-assign]
    svc._users.set_default_model_profile = AsyncMock()  # type: ignore[method-assign]

    views = await svc.list_profiles("u1")
    assert len(views) == 1
    assert views[0].id == "user-combo-1"
    assert views[0].is_default is True
    svc._users.set_default_model_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_expand_dormant_system_falls_to_byok_coherent(monkeypatch):
    """Unavailable system preset → BYOK selection; name/origin match (not GLM-5.2 + byok)."""
    from agentcore.llm.resolve import ModelSelection

    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_listable_model_ids",
        lambda: ["glm-5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: False,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "agentcore.llm.model_profiles._provider_first_fallback",
        AsyncMock(
            return_value=ModelSelection(
                model="user-flash", origin="byok", provider_id="p1"
            )
        ),
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=_glm_preset_id())  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[])  # type: ignore[method-assign]
    svc._repo.get = AsyncMock(return_value=None)  # type: ignore[method-assign]

    expanded = await svc.expand("u1", None)
    assert expanded.main.origin == "byok"
    assert expanded.main.model == "user-flash"
    assert expanded.main.provider_id == "p1"
    assert expanded.kind == "implicit"
    assert "GLM-5.2" not in expanded.name
    assert "glm-5.2" not in expanded.name
    assert expanded.profile_id != _glm_preset_id()


@pytest.mark.asyncio
async def test_validate_slot_platform_requires_catalog_visible(monkeypatch):
    from agentcore.core.errors import ValidationError
    from agentcore.llm.model_profiles import ProfileSlot

    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: False,
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.is_platform_available",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    with pytest.raises(ValidationError, match="不可用平台模型"):
        await svc._validate_slot(
            "u1",
            ProfileSlot(origin="platform", model="glm-5.2", provider_id=None),
            label="main",
        )
