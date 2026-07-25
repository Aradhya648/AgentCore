"""Unit tests for fixed platform system presets (5.2 / grok-4.5)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.llm.model_profiles import (
    SYSTEM_PRESETS,
    SYSTEM_PROFILE_52,
    SYSTEM_PROFILE_DEFAULT,
    SYSTEM_PROFILE_GROK,
    LlmModelProfileService,
    is_system_profile_id,
    resolve_system_preset_main,
)


def test_system_preset_constants_and_ids():
    assert SYSTEM_PROFILE_DEFAULT is SYSTEM_PROFILE_52
    assert SYSTEM_PRESETS[SYSTEM_PROFILE_52] == "5.2"
    assert SYSTEM_PRESETS[SYSTEM_PROFILE_GROK] == "grok-4.5"
    assert is_system_profile_id(SYSTEM_PROFILE_52)
    assert not is_system_profile_id("00000000-0000-4000-8000-000000000002")
    assert not is_system_profile_id("00000000-0000-4000-8000-000000000001")


def test_resolve_system_preset_main_is_fixed(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_model_ids",
        lambda: ["other-model"],
    )
    sel = resolve_system_preset_main(SYSTEM_PROFILE_52)
    assert sel.model == "5.2"
    assert sel.origin == "platform"
    assert sel.provider_id is None


@pytest.mark.asyncio
async def test_list_profiles_hides_missing_catalog_models(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_model_ids",
        lambda: ["5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[])  # type: ignore[method-assign]

    views = await svc.list_profiles("u1")
    assert [v.id for v in views] == [SYSTEM_PROFILE_52]
    assert views[0].name == "5.2"
    assert views[0].is_default is True
    assert views[0].main.model == "5.2"
    assert views[0].worker is None
    assert views[0].background is None


@pytest.mark.asyncio
async def test_list_profiles_marks_default_when_both_present(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_model_ids",
        lambda: ["5.2", "grok-4.5"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.list_for_user = AsyncMock(return_value=[])  # type: ignore[method-assign]

    views = await svc.list_profiles("u1")
    assert [v.id for v in views] == [SYSTEM_PROFILE_52, SYSTEM_PROFILE_GROK]
    assert views[0].is_default is True
    assert views[1].is_default is False
    assert views[1].name == "Grok 4.5"


@pytest.mark.asyncio
async def test_expand_none_and_dangling_fall_back_to_52(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_model_ids",
        lambda: ["5.2", "grok-4.5"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    svc._repo.get = AsyncMock(return_value=None)  # type: ignore[method-assign]

    expanded = await svc.expand("u1", None)
    assert expanded.profile_id == SYSTEM_PROFILE_52
    assert expanded.main.model == "5.2"
    assert expanded.name == "5.2"

    dangling = await svc.expand("u1", "00000000-0000-4000-8000-000000000002")
    assert dangling.profile_id == SYSTEM_PROFILE_52
    assert dangling.main.model == "5.2"


@pytest.mark.asyncio
async def test_expand_unavailable_grok_falls_back_to_52(monkeypatch):
    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_model_ids",
        lambda: ["5.2"],
    )
    monkeypatch.setattr(
        "agentcore.billing.preference.platform_billing_selectable",
        lambda: True,
    )
    svc = LlmModelProfileService(MagicMock())
    svc._default_id = AsyncMock(return_value=None)  # type: ignore[method-assign]

    expanded = await svc.expand("u1", SYSTEM_PROFILE_GROK)
    assert expanded.profile_id == SYSTEM_PROFILE_52
    assert expanded.main.model == "5.2"


@pytest.mark.asyncio
async def test_set_default_rejects_unavailable_system_preset(monkeypatch):
    from agentcore.core.errors import ValidationError

    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_model_ids",
        lambda: ["5.2"],
    )
    svc = LlmModelProfileService(MagicMock())
    with pytest.raises(ValidationError, match="不可用"):
        await svc.set_default("u1", SYSTEM_PROFILE_GROK)


@pytest.mark.asyncio
async def test_ensure_rejects_unavailable_system_preset(monkeypatch):
    from agentcore.core.errors import ValidationError

    monkeypatch.setattr(
        "agentcore.llm.catalog._platform_model_ids",
        lambda: ["5.2"],
    )
    svc = LlmModelProfileService(MagicMock())
    with pytest.raises(ValidationError, match="不可用"):
        await svc.ensure_profile_usable("u1", SYSTEM_PROFILE_GROK)
