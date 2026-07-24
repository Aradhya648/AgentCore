"""Unit tests for LlmProviderService (BYOK 多服务商 write path)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcore.config import settings
from agentcore.core.errors import (
    KeyStorageUnavailableError,
    LLMError,
    NotFoundError,
    ValidationError,
)
from agentcore.llm.credentials import LLMCredentials
from agentcore.llm.profiles import DEEPSEEK_V4_FLASH
from agentcore.llm.provider_service import LlmDefaultPointer, LlmProviderService

pytestmark = pytest.mark.anyio


def _row(**kwargs):
    defaults = {
        "id": "prov-1",
        "user_id": "u1",
        "label": "DeepSeek",
        "api_key_enc": b"cipher",
        "base_url": settings.platform_base_url,
        "default_model": DEEPSEEK_V4_FLASH,
        "price_cache_hit": None,
        "price_cache_miss": None,
        "price_output": None,
        "supports_tools": None,
        "status": "unchecked",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _user(**kwargs):
    defaults = {
        "user_id": "u1",
        "default_chat_provider_id": None,
        "default_chat_model": None,
        "default_background_provider_id": None,
        "default_background_model": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.fixture
def service():
    svc = LlmProviderService(MagicMock())
    svc._repo = MagicMock()
    svc._users = MagicMock()
    svc._repo.count_for_user = AsyncMock(return_value=0)
    svc._repo.create = AsyncMock(return_value=_row())
    svc._repo.get = AsyncMock(return_value=_row())
    svc._repo.list_for_user = AsyncMock(return_value=[_row()])
    svc._repo.update = AsyncMock(return_value=_row())
    svc._repo.update_status = AsyncMock()
    svc._repo.update_supports_tools = AsyncMock()
    svc._repo.first_for_user = AsyncMock(return_value=None)
    svc._repo.delete = AsyncMock(return_value=True)
    svc._users.get_by_id = AsyncMock(return_value=_user())
    svc._users.set_llm_defaults = AsyncMock()
    return svc


def _enc():
    enc = MagicMock()
    enc.encrypt.return_value = b"cipher"
    enc.decrypt.return_value = b"sk-secret-1234"
    return enc


async def test_create_provider_first_becomes_chat_default(service):
    with patch.object(service, "_encryptor", return_value=_enc()):
        service._users.get_by_id = AsyncMock(
            return_value=_user(default_chat_provider_id="prov-1", default_chat_model=DEEPSEEK_V4_FLASH)
        )
        view = await service.create_provider(
            "u1", label="DeepSeek", api_key="sk-secret-1234"
        )
    # The account chat default pointer was auto-set to the first provider.
    service._users.set_llm_defaults.assert_awaited_once_with(
        "u1", chat_provider_id="prov-1", chat_model=DEEPSEEK_V4_FLASH
    )
    assert view.id == "prov-1"
    assert view.is_default_chat is True
    assert view.masked_key == "••••1234"


async def test_create_provider_second_does_not_reset_default(service):
    service._repo.count_for_user = AsyncMock(return_value=1)  # already has one
    with patch.object(service, "_encryptor", return_value=_enc()):
        await service.create_provider("u1", label="Kimi", api_key="sk-second-key")
    service._users.set_llm_defaults.assert_not_awaited()


async def test_create_provider_rejects_empty_key(service):
    with pytest.raises(ValidationError):
        await service.create_provider("u1", label="X", api_key="   ")


async def test_create_provider_without_master_key_raises(service):
    with (
        patch.object(service, "_encryptor", return_value=None),
        pytest.raises(KeyStorageUnavailableError),
    ):
        await service.create_provider("u1", label="X", api_key="sk-x")


async def test_create_provider_rejects_partial_price_card(service):
    with (
        patch.object(service, "_encryptor", return_value=_enc()),
        pytest.raises(ValidationError),
    ):
        await service.create_provider(
            "u1", label="X", api_key="sk-x", price_cache_miss="1.0"
        )  # output missing


async def test_list_providers_reports_pointers_and_free_tier(service, monkeypatch):
    monkeypatch.setattr(settings, "platform_free_tier_enabled", True)
    monkeypatch.setattr(settings, "platform_api_key", "sk-platform")
    monkeypatch.setattr(settings, "billing_mode", "byok")
    service._repo.list_for_user = AsyncMock(return_value=[])  # keyless
    service._users.get_by_id = AsyncMock(return_value=_user())
    view = await service.list_providers("u1")
    assert view.providers == []
    assert view.default_chat is None
    assert view.platform_available is True
    assert view.free_tier_active is True  # keyless + free tier + platform


async def test_list_providers_pointer_reflects_default(service):
    row = _row(id="prov-1")
    service._repo.list_for_user = AsyncMock(return_value=[row])
    service._users.get_by_id = AsyncMock(
        return_value=_user(default_chat_provider_id="prov-1", default_chat_model="deepseek-v4-pro")
    )
    with patch.object(service, "_encryptor", return_value=_enc()):
        view = await service.list_providers("u1")
    assert view.default_chat is not None
    assert view.default_chat.provider_id == "prov-1"
    assert view.default_chat.model == "deepseek-v4-pro"
    assert view.providers[0].is_default_chat is True


class _FakeProbeProvider:
    def __init__(self, *, fail: bool, supports_tools: bool | None) -> None:
        self._fail = fail
        self._supports_tools = supports_tools
        self.probe_model: str | None = None

    async def probe(self, *, model: str) -> None:
        self.probe_model = model
        if self._fail:
            raise LLMError("bad key")

    async def probe_tools(self, *, model: str) -> bool | None:
        return self._supports_tools

    async def close(self) -> None:
        pass


async def test_test_provider_records_active_and_tools(service):
    # First get = the row to probe; second get = the fresh row after status persisted.
    service._repo.get = AsyncMock(
        side_effect=[
            _row(api_key_enc=b"x"),
            _row(api_key_enc=b"x", status="active", supports_tools=True),
        ]
    )
    creds = LLMCredentials(
        api_key="sk-abc", base_url="https://api.openai.com/v1", default_model="gpt-4o"
    )
    fake = _FakeProbeProvider(fail=False, supports_tools=True)
    with (
        patch(
            "agentcore.llm.provider_service.resolve_provider_credentials",
            AsyncMock(return_value=creds),
        ),
        patch("agentcore.llm.provider_service.build_provider", return_value=fake),
        patch.object(service, "_encryptor", return_value=_enc()),
    ):
        view = await service.test_provider("u1", "prov-1")
    assert fake.probe_model == "gpt-4o"
    assert view.status == "active"
    service._repo.update_status.assert_awaited_once_with("prov-1", "active")
    service._repo.update_supports_tools.assert_awaited_once_with("prov-1", True)


async def test_test_provider_missing_raises(service):
    service._repo.get = AsyncMock(return_value=None)
    with pytest.raises(NotFoundError):
        await service.test_provider("u1", "missing")


async def test_delete_provider_repoints_chat_default(service):
    # The deleted provider WAS the chat default; a remaining provider takes over.
    service._users.get_by_id = AsyncMock(
        return_value=_user(default_chat_provider_id="prov-1", default_chat_model="m")
    )
    service._repo.first_for_user = AsyncMock(return_value=_row(id="prov-2", default_model="m2"))
    await service.delete_provider("u1", "prov-1")
    service._users.set_llm_defaults.assert_awaited_once_with(
        "u1", chat_provider_id="prov-2", chat_model="m2"
    )


async def test_delete_provider_clears_default_when_last(service):
    service._users.get_by_id = AsyncMock(
        return_value=_user(default_chat_provider_id="prov-1", default_chat_model="m")
    )
    service._repo.first_for_user = AsyncMock(return_value=None)  # nothing left
    await service.delete_provider("u1", "prov-1")
    service._users.set_llm_defaults.assert_awaited_once_with(
        "u1", chat_provider_id=None, chat_model=None
    )


async def test_delete_provider_missing_raises(service):
    service._repo.delete = AsyncMock(return_value=False)
    with pytest.raises(NotFoundError):
        await service.delete_provider("u1", "missing")


async def test_set_defaults_validates_ownership(service):
    service._repo.get = AsyncMock(return_value=None)  # not owned
    with pytest.raises(ValidationError):
        await service.set_defaults(
            "u1",
            chat=LlmDefaultPointer(provider_id="ghost", model="m"),
            background=None,
            set_chat=True,
            set_background=False,
        )
