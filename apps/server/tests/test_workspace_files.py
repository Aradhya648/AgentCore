"""Tests for the workspace file I/O service (upload / download / list).

End-to-end over the cloud-mode backend: resolves a conversation's workspace via
``locate`` and round-trips binary content through it. ``data_dir`` is redirected
to ``tmp_path`` so nothing touches the real ./data tree.
"""

from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.workspace.files import download_file, list_files, upload_file
from agentcore.workspace.protocol import NotAFile, OutsideWorkspace, PathNotFound


@pytest.fixture(autouse=True)
def _redirect_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


async def test_upload_then_download_roundtrip():
    blob = bytes(range(256))
    written = await upload_file(
        user_id="u1", folder_id="f1", conversation_id="c1", path="in/data.bin", data=blob
    )
    assert written == 256
    got = await download_file(
        user_id="u1", folder_id="f1", conversation_id="c1", path="in/data.bin"
    )
    assert got == blob


async def test_uploaded_file_appears_in_listing():
    await upload_file(user_id="u1", folder_id="f1", conversation_id="c1", path="top.txt", data=b"x")
    await upload_file(
        user_id="u1", folder_id="f1", conversation_id="c1", path="sub/deep.txt", data=b"y"
    )
    top = {e.path for e in await list_files(user_id="u1", folder_id="f1", conversation_id="c1")}
    assert "top.txt" in top

    deep = {
        e.path
        for e in await list_files(
            user_id="u1", folder_id="f1", conversation_id="c1", recursive=True
        )
    }
    assert "sub/deep.txt" in deep


async def test_download_missing_raises():
    with pytest.raises(PathNotFound):
        await download_file(user_id="u1", folder_id="f1", conversation_id="c1", path="ghost.bin")


async def test_download_directory_raises_not_a_file():
    await upload_file(
        user_id="u1", folder_id="f1", conversation_id="c1", path="d/inner.txt", data=b"x"
    )
    with pytest.raises(NotAFile):
        await download_file(user_id="u1", folder_id="f1", conversation_id="c1", path="d")


async def test_upload_traversal_is_blocked():
    with pytest.raises(OutsideWorkspace):
        await upload_file(
            user_id="u1",
            folder_id="f1",
            conversation_id="c1",
            path="../escape.bin",
            data=b"x",
        )


async def test_conversation_scratch_spaces_are_independent_when_bare():
    """Bare chats (folder_id=None) each own an independent scratch."""
    await upload_file(
        user_id="u1", folder_id=None, conversation_id="c1", path="shared.txt", data=b"v"
    )
    with pytest.raises(PathNotFound):
        await download_file(
            user_id="u1", folder_id=None, conversation_id="c2", path="shared.txt"
        )


async def test_project_conversations_share_folder_space():
    """Siblings in the same project share one workspace root."""
    await upload_file(
        user_id="u1", folder_id="f1", conversation_id="c1", path="shared.txt", data=b"v"
    )
    got = await download_file(
        user_id="u1", folder_id="f1", conversation_id="c2", path="shared.txt"
    )
    assert got == b"v"
