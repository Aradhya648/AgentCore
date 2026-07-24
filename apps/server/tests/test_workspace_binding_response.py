"""Workspace binding GET 口径 = turn routing (explicit vs container / project inherit)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentcore.api.routes.conversations.binding import _binding_response


def _folder_repo(folder=None):
    repo = MagicMock()
    repo.get_by_id_unscoped = AsyncMock(return_value=folder)
    return repo


@pytest.mark.asyncio
async def test_binding_response_cloud_when_unbound():
    conv = SimpleNamespace(folder_id=None, local_root_id=None, local_container_root_id=None)
    r = await _binding_response(conv, folder_repo=_folder_repo())  # type: ignore[arg-type]
    assert r.mode == "cloud"
    assert r.scope == "conversation"
    assert r.root_id is None
    assert r.source is None


@pytest.mark.asyncio
async def test_binding_response_prefers_explicit_over_container():
    conv = SimpleNamespace(
        folder_id=None,
        local_root_id="explicit-root",
        local_container_root_id="container-root",
    )
    r = await _binding_response(conv, folder_repo=_folder_repo())  # type: ignore[arg-type]
    assert r.mode == "local"
    assert r.root_id == "explicit-root"
    assert r.source == "explicit"


@pytest.mark.asyncio
async def test_binding_response_container_default_is_local():
    conv = SimpleNamespace(
        folder_id=None, local_root_id=None, local_container_root_id="container-abc"
    )
    r = await _binding_response(conv, folder_repo=_folder_repo())  # type: ignore[arg-type]
    assert r.mode == "local"
    assert r.root_id == "container-abc"
    assert r.source == "container"


@pytest.mark.asyncio
async def test_binding_response_inherits_project_local():
    folder = SimpleNamespace(local_root_id="folder-root", local_subpath="src")
    conv = SimpleNamespace(
        folder_id="f1",
        local_root_id=None,
        local_container_root_id="ignored",
    )
    r = await _binding_response(conv, folder_repo=_folder_repo(folder))  # type: ignore[arg-type]
    assert r.mode == "local"
    assert r.scope == "folder"
    assert r.root_id == "folder-root"
    assert r.source == "explicit"
