"""Integration tests for the workspace file + snapshot HTTP routes.

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Covers the auth gate, per-user scoping (IDOR), the raw-body upload / download
round-trip, and the snapshot create → list → restore → download lifecycle.

``data_dir`` and the storage backend are redirected to a tmp dir so the routes
never write under the real ./data tree; the lru-cached storage factory is
cleared around each test so the redirect takes effect.
"""

import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from agentcore.config import settings
from agentcore.storage.factory import build_storage_provider
from tests.integration.conftest import register_and_login


def _init_source_repo(path: Path) -> None:
    """Create a one-commit git repo at ``path`` (cloneable over file://)."""
    path.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, env=env)

    run("init")
    run("config", "user.email", "tester@example.com")
    run("config", "user.name", "Tester")
    (path / "README.md").write_text("hello clone\n", encoding="utf-8")
    run("add", "README.md")
    run("commit", "-m", "init")


@pytest.fixture
def _fs_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    build_storage_provider.cache_clear()
    try:
        yield
    finally:
        build_storage_provider.cache_clear()


async def _new_conversation(client: httpx.AsyncClient) -> str:
    r = await client.post("/v1/conversations", json={})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_workspace_files_requires_auth(client):
    r = await client.get("/v1/conversations/whatever/workspace/files")
    assert r.status_code == 401


async def test_create_conversation_records_local_intent(client, _fs_data_dir):
    """A desktop 裸聊 is born carrying its local-container intent (工作区对称化 D1a).

    Storing it on the conversation (vs. per-turn) is what makes every later promotion
    path — Agent turn or panel write — agree on locality. The field round-trips on the
    read model; it's recorded only for a 裸聊 (a foldered chat inherits its folder's
    binding, so the field is dropped).
    """
    await register_and_login(client, "wsintent")

    r = await client.post("/v1/conversations", json={"local_container_root_id": "root-abc"})
    assert r.status_code == 201, r.text
    conv_id = r.json()["id"]
    assert r.json()["local_container_root_id"] == "root-abc"

    r = await client.get(f"/v1/conversations/{conv_id}")
    assert r.json()["local_container_root_id"] == "root-abc"

    # Moot once foldered: a chat born into a folder inherits its binding, so the
    # standalone intent is not recorded even if the client passes one.
    folder = await client.post("/v1/folders", json={"name": "proj", "mode": "cloud"})
    assert folder.status_code == 201, folder.text
    r = await client.post(
        "/v1/conversations",
        json={"folder_id": folder.json()["id"], "local_container_root_id": "root-xyz"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["local_container_root_id"] is None


async def test_project_conversations_share_cloud_workspace(client, _fs_data_dir):
    """Cloud project chats inherit shared folder:<id> space (not per-conv scratch)."""
    await register_and_login(client, "wsshare")
    folder = (
        await client.post("/v1/folders", json={"name": "Shared", "mode": "cloud"})
    ).json()
    folder_id = folder["id"]
    a = (
        await client.post(
            "/v1/conversations", json={"title": "a", "folder_id": folder_id}
        )
    ).json()["id"]
    b = (
        await client.post(
            "/v1/conversations", json={"title": "b", "folder_id": folder_id}
        )
    ).json()["id"]

    body = b"shared-bytes"
    r = await client.put(
        f"/v1/conversations/{a}/workspace/files/notes/a.txt", content=body
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/v1/conversations/{b}/workspace/files/notes/a.txt")
    assert r.status_code == 200
    assert r.content == body

    r = await client.get(f"/v1/workspaces/folder:{folder_id}/files", params={"recursive": True})
    assert r.status_code == 200
    assert "notes/a.txt" in {e["path"] for e in r.json()["data"]}


async def test_upload_list_download_roundtrip(client, _fs_data_dir):
    await register_and_login(client, "wsuser1")
    conv_id = await _new_conversation(client)

    body = b"hello-from-upload\x00\x01"  # includes non-text bytes
    r = await client.put(
        f"/v1/conversations/{conv_id}/workspace/files/notes/hello.bin", content=body
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"path": "notes/hello.bin", "size_bytes": len(body)}

    r = await client.get(
        f"/v1/conversations/{conv_id}/workspace/files", params={"recursive": "true"}
    )
    assert r.status_code == 200, r.text
    paths = {e["path"] for e in r.json()["data"]}
    assert "notes/hello.bin" in paths

    r = await client.get(f"/v1/conversations/{conv_id}/workspace/files/notes/hello.bin")
    assert r.status_code == 200
    assert r.content == body
    assert 'filename="hello.bin"' in r.headers.get("content-disposition", "")

    r = await client.get(f"/v1/conversations/{conv_id}/workspace/files/ghost.txt")
    assert r.status_code == 404


async def test_delete_and_move_workspace_files(client, _fs_data_dir):
    await register_and_login(client, "wsmover")
    conv_id = await _new_conversation(client)

    await client.put(f"/v1/conversations/{conv_id}/workspace/files/a.txt", content=b"A")
    await client.put(f"/v1/conversations/{conv_id}/workspace/files/keep.txt", content=b"K")

    # Rename a.txt -> docs/b.txt (move creates the parent dir).
    r = await client.post(
        f"/v1/conversations/{conv_id}/workspace/move",
        json={"src": "a.txt", "dst": "docs/b.txt"},
    )
    assert r.status_code == 200, r.text
    assert (
        await client.get(f"/v1/conversations/{conv_id}/workspace/files/a.txt")
    ).status_code == 404
    r = await client.get(f"/v1/conversations/{conv_id}/workspace/files/docs/b.txt")
    assert r.status_code == 200 and r.content == b"A"

    # Moving onto an existing path is refused (422), leaving the target intact.
    r = await client.post(
        f"/v1/conversations/{conv_id}/workspace/move",
        json={"src": "docs/b.txt", "dst": "keep.txt"},
    )
    assert r.status_code == 422, r.text
    assert (
        await client.get(f"/v1/conversations/{conv_id}/workspace/files/keep.txt")
    ).content == b"K"

    # Delete the file; deleting a missing path is a 404.
    r = await client.delete(f"/v1/conversations/{conv_id}/workspace/files/docs/b.txt")
    assert r.status_code == 200, r.text
    assert (
        await client.get(f"/v1/conversations/{conv_id}/workspace/files/docs/b.txt")
    ).status_code == 404
    assert (
        await client.delete(f"/v1/conversations/{conv_id}/workspace/files/ghost.txt")
    ).status_code == 404


async def test_create_workspace_dir(client, _fs_data_dir):
    await register_and_login(client, "wsmkdir")
    conv_id = await _new_conversation(client)

    # Create a nested folder (parents are created).
    r = await client.post(f"/v1/conversations/{conv_id}/workspace/dirs", json={"path": "src/lib"})
    assert r.status_code == 200, r.text

    r = await client.get(
        f"/v1/conversations/{conv_id}/workspace/files", params={"recursive": "true"}
    )
    dirs = {e["path"] for e in r.json()["data"] if e["is_dir"]}
    assert {"src", "src/lib"} <= dirs

    # Recreating an existing folder is refused (422).
    r = await client.post(f"/v1/conversations/{conv_id}/workspace/dirs", json={"path": "src/lib"})
    assert r.status_code == 422, r.text

    # A freshly made folder is a valid move destination.
    await client.put(f"/v1/conversations/{conv_id}/workspace/files/x.txt", content=b"X")
    r = await client.post(
        f"/v1/conversations/{conv_id}/workspace/move",
        json={"src": "x.txt", "dst": "src/lib/x.txt"},
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/v1/conversations/{conv_id}/workspace/files/src/lib/x.txt")
    assert r.status_code == 200 and r.content == b"X"


async def test_snapshot_create_list_restore_download(client, _fs_data_dir):
    await register_and_login(client, "wsuser2")
    conv_id = await _new_conversation(client)

    # Seed v1, snapshot it, then overwrite with v2.
    await client.put(f"/v1/conversations/{conv_id}/workspace/files/doc.txt", content=b"v1")
    r = await client.post(f"/v1/conversations/{conv_id}/snapshots", json={"label": "milestone"})
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["label"] == "milestone"
    sid = snap["snapshot_id"]

    r = await client.get(f"/v1/conversations/{conv_id}/snapshots")
    assert r.status_code == 200
    assert sid in {s["snapshot_id"] for s in r.json()["data"]}

    await client.put(f"/v1/conversations/{conv_id}/workspace/files/doc.txt", content=b"v2")

    # Restore brings v1 back.
    r = await client.post(f"/v1/conversations/{conv_id}/snapshots/{sid}/restore")
    assert r.status_code == 200, r.text
    r = await client.get(f"/v1/conversations/{conv_id}/workspace/files/doc.txt")
    assert r.content == b"v1"

    # Download the archive (zip bytes).
    r = await client.get(f"/v1/conversations/{conv_id}/snapshots/{sid}/download")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"
    assert r.headers["content-type"] == "application/zip"

    # Unknown snapshot id → 404 on both restore and download.
    assert (
        await client.post(f"/v1/conversations/{conv_id}/snapshots/nope/restore")
    ).status_code == 404
    assert (
        await client.get(f"/v1/conversations/{conv_id}/snapshots/nope/download")
    ).status_code == 404


async def test_clone_repo_into_workspace(client, _fs_data_dir, tmp_path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    src = tmp_path / "source-repo"
    _init_source_repo(src)

    # URL policy (http-only) is unit-tested; stub it so the local file:// source
    # can drive the route end-to-end without a network repo.
    from agentcore.workspace import git as gitmod

    monkeypatch.setattr(gitmod, "_validate_url", lambda url: None)

    await register_and_login(client, "wscloner")
    conv_id = await _new_conversation(client)

    r = await client.post(
        f"/v1/conversations/{conv_id}/workspace/clone",
        json={"repo_url": src.as_uri(), "dest": "i"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "i"

    r = await client.get(f"/v1/conversations/{conv_id}/workspace/files/i/README.md")
    assert r.status_code == 200
    # Normalize EOL: git on Windows may apply autocrlf on checkout.
    assert r.content.replace(b"\r\n", b"\n") == b"hello clone\n"

    # Cloning again into the same non-empty dest is refused (422).
    r = await client.post(
        f"/v1/conversations/{conv_id}/workspace/clone",
        json={"repo_url": src.as_uri(), "dest": "i"},
    )
    assert r.status_code == 422, r.text


async def test_other_user_cannot_touch_workspace(client, new_client, _fs_data_dir):
    """A conversation's workspace is scoped to its owner (IDOR-safe → 404)."""
    await register_and_login(client, "owner")
    conv_id = await _new_conversation(client)
    await client.put(f"/v1/conversations/{conv_id}/workspace/files/secret.txt", content=b"top")

    async with new_client() as other:
        await register_and_login(other, "intruder")
        assert (await other.get(f"/v1/conversations/{conv_id}/workspace/files")).status_code == 404
        assert (
            await other.get(f"/v1/conversations/{conv_id}/workspace/files/secret.txt")
        ).status_code == 404
        assert (await other.get(f"/v1/conversations/{conv_id}/snapshots")).status_code == 404
        # Mutating routes are owner-scoped too (404, not a silent delete/move).
        assert (
            await other.delete(f"/v1/conversations/{conv_id}/workspace/files/secret.txt")
        ).status_code == 404
        assert (
            await other.post(
                f"/v1/conversations/{conv_id}/workspace/move",
                json={"src": "secret.txt", "dst": "stolen.txt"},
            )
        ).status_code == 404
