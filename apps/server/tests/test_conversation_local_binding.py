"""Unit tests for per-conversation / project local binding resolution."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.conversation.common import resolve_local_binding
from agentcore.conversation.scratch import bare_chat_local_subpath
from agentcore.db.models import Conversation, Folder


def _conv(**kwargs) -> Conversation:
    base = {"id": "11111111-1111-1111-1111-111111111111", "title": "t"}
    base.update(kwargs)
    return Conversation(**base)


def _folder(**kwargs) -> Folder:
    base = {
        "id": "22222222-2222-2222-2222-222222222222",
        "user_id": "u1",
        "name": "Proj",
    }
    base.update(kwargs)
    return Folder(**base)


@pytest.mark.asyncio
async def test_resolve_local_binding_prefers_explicit_root():
    conv = _conv(local_root_id="explicit", local_container_root_id="container")
    binding = await resolve_local_binding(None, conv)  # type: ignore[arg-type]
    assert binding is not None
    assert binding.root_id == "explicit"
    assert binding.subpath == bare_chat_local_subpath(conv.id)


@pytest.mark.asyncio
async def test_bare_chat_empty_subpath_becomes_conversations_id():
    conv = _conv(local_root_id=None, local_container_root_id="container-abc", local_subpath=None)
    binding = await resolve_local_binding(None, conv)  # type: ignore[arg-type]
    assert binding is not None
    assert binding.root_id == "container-abc"
    assert binding.subpath == f"conversations/{conv.id}"


@pytest.mark.asyncio
async def test_bare_chat_explicit_subpath_preserved():
    conv = _conv(
        local_root_id=None,
        local_container_root_id="container-abc",
        local_subpath="proj",
    )
    binding = await resolve_local_binding(None, conv)  # type: ignore[arg-type]
    assert binding is not None
    assert binding.root_id == "container-abc"
    assert binding.subpath == "proj"


@pytest.mark.asyncio
async def test_resolve_local_binding_none_when_unbound():
    conv = _conv(local_root_id=None, local_container_root_id=None)
    assert await resolve_local_binding(None, conv) is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_resolve_local_binding_inherits_project_local(monkeypatch):
    folder = _folder(local_root_id="folder-root", local_subpath="src")
    conv = _conv(folder_id=folder.id, local_container_root_id="should-ignore")

    mock_repo = MagicMock()
    mock_repo.get_by_id_unscoped = AsyncMock(return_value=folder)
    monkeypatch.setattr(
        "agentcore.db.repositories.FolderRepository",
        lambda session: mock_repo,
    )

    binding = await resolve_local_binding(MagicMock(), conv)
    assert binding is not None
    assert binding.root_id == "folder-root"
    assert binding.subpath == "src"
    assert binding.root_label == "Proj"
    # Project binding must NOT inject conversations/<id>.
    assert not binding.subpath.startswith("conversations/")


@pytest.mark.asyncio
async def test_resolve_local_binding_cloud_project_returns_none(monkeypatch):
    folder = _folder(local_root_id=None, local_subpath=None)
    conv = _conv(folder_id=folder.id, local_container_root_id="should-ignore")

    mock_repo = MagicMock()
    mock_repo.get_by_id_unscoped = AsyncMock(return_value=folder)
    monkeypatch.setattr(
        "agentcore.db.repositories.FolderRepository",
        lambda session: mock_repo,
    )

    assert await resolve_local_binding(MagicMock(), conv) is None
