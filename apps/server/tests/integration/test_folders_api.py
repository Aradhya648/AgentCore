"""Integration tests for folder CRUD + conversation grouping (项目即工作区).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Covers create modes, birth-time membership, soft-delete archives (no ungroup),
permanent wipe (conversations + cloud space), absence of PATCH …/folder, and IDOR isolation.
"""

from pathlib import Path

import httpx
import pytest

import agentcore.folders.permanent_delete as permanent_delete_mod
from agentcore.config import settings
from agentcore.db.repositories import MessageRepository
from agentcore.storage.factory import build_storage_provider
from agentcore.workspace.locate import workspace_root_path
from tests.integration.conftest import register_and_login

_ROOT = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def _fs_data_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    build_storage_provider.cache_clear()
    try:
        yield tmp_path
    finally:
        build_storage_provider.cache_clear()


async def _new_conversation(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_message(session_factory, conversation_id: str) -> None:
    async with session_factory() as session:
        await MessageRepository(session).create(
            conversation_id=conversation_id, role="user", content="hi"
        )


async def _create_cloud_folder(client: httpx.AsyncClient, name: str) -> str:
    r = await client.post("/v1/folders", json={"name": name, "mode": "cloud"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_folders_require_auth(client):
    assert (await client.get("/v1/folders")).status_code == 401
    assert (await client.get("/v1/conversations/grouped")).status_code == 401


async def test_create_cloud_and_local_folders(client, make_invite):
    code = await make_invite("INV-F1")
    await register_and_login(client, code, "folderuser1")

    r = await client.post("/v1/folders", json={"name": "Cloud Proj", "mode": "cloud"})
    assert r.status_code == 201, r.text
    cloud = r.json()
    assert cloud["name"] == "Cloud Proj"
    assert cloud["mode"] == "cloud"
    assert cloud["local_root_id"] is None
    assert cloud["local_subpath"] is None
    assert "local_dir" not in cloud

    r = await client.post(
        "/v1/folders",
        json={
            "name": "Local Proj",
            "mode": "local",
            "local_root_id": _ROOT,
            "local_subpath": "apps",
        },
    )
    assert r.status_code == 201, r.text
    local = r.json()
    assert local["mode"] == "local"
    assert local["local_root_id"] == _ROOT
    assert local["local_subpath"] == "apps"

    r = await client.get("/v1/folders")
    assert r.status_code == 200, r.text
    assert {f["id"] for f in r.json()} == {cloud["id"], local["id"]}


async def test_create_folder_requires_mode(client, make_invite):
    code = await make_invite("INV-F-MODE")
    await register_and_login(client, code, "foldermode")
    assert (await client.post("/v1/folders", json={"name": "NoMode"})).status_code == 422


async def test_create_local_folder_requires_root(client, make_invite):
    code = await make_invite("INV-F-LROOT")
    await register_and_login(client, code, "folderlroot")
    r = await client.post("/v1/folders", json={"name": "Local", "mode": "local"})
    assert r.status_code == 422, r.text


async def test_create_cloud_folder_rejects_local_binding(client, make_invite):
    code = await make_invite("INV-F12")
    await register_and_login(client, code, "folderuser12")
    r = await client.post(
        "/v1/folders",
        json={"name": "Cloud", "mode": "cloud", "local_root_id": _ROOT},
    )
    assert r.status_code == 422, r.text


async def test_create_rejects_local_dir_field(client, make_invite):
    code = await make_invite("INV-F-LDIR")
    await register_and_login(client, code, "folderldir")
    r = await client.post(
        "/v1/folders",
        json={"name": "X", "mode": "cloud", "local_dir": "/tmp"},
    )
    assert r.status_code == 422, r.text


async def test_grouped_reflects_birth_membership(client, make_invite):
    code = await make_invite("INV-F2")
    await register_and_login(client, code, "folderuser2")

    folder_id = await _create_cloud_folder(client, "Proj")
    grouped_conv_r = await client.post(
        "/v1/conversations", json={"title": "in folder", "folder_id": folder_id}
    )
    assert grouped_conv_r.status_code == 201, grouped_conv_r.text
    grouped_conv = grouped_conv_r.json()["id"]
    loose_conv = await _new_conversation(client, "loose")

    body = (await client.get("/v1/conversations/grouped")).json()
    group = body["folders"][0]
    assert group["mode"] == "cloud"
    assert [c["id"] for c in group["conversations"]] == [grouped_conv]
    assert [c["id"] for c in body["ungrouped"]] == [loose_conv]


async def test_patch_conversation_folder_gone(client, make_invite):
    """Birth-time membership: PATCH /conversations/{id}/folder no longer exists."""
    code = await make_invite("INV-F7")
    await register_and_login(client, code, "folderuser7")
    folder_id = await _create_cloud_folder(client, "Proj")
    conv = await _new_conversation(client, "started")

    r = await client.patch(
        f"/v1/conversations/{conv}/folder", json={"folder_id": folder_id}
    )
    assert r.status_code == 404, r.text


async def test_create_in_folder_files_at_creation(client, make_invite):
    code = await make_invite("INV-F9")
    await register_and_login(client, code, "folderuser9")
    folder_id = await _create_cloud_folder(client, "Born")

    r = await client.post(
        "/v1/conversations", json={"title": "in folder", "folder_id": folder_id}
    )
    assert r.status_code == 201, r.text
    conv_id = r.json()["id"]
    assert r.json()["folder_id"] == folder_id
    assert r.json()["local_container_root_id"] is None

    body = (await client.get("/v1/conversations/grouped")).json()
    assert [c["id"] for c in body["folders"][0]["conversations"]] == [conv_id]


async def test_create_in_missing_folder_404(client, make_invite):
    code = await make_invite("INV-F10")
    await register_and_login(client, code, "folderuser10")
    r = await client.post(
        "/v1/conversations",
        json={"title": "x", "folder_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404, r.text


async def test_grouped_reports_message_count(client, make_invite, session_factory):
    code = await make_invite("INV-F11")
    await register_and_login(client, code, "folderuser11")
    conv = await _new_conversation(client, "counts")

    body = (await client.get("/v1/conversations/grouped")).json()
    assert body["ungrouped"][0]["message_count"] == 0

    await _seed_message(session_factory, conv)
    await _seed_message(session_factory, conv)

    body = (await client.get("/v1/conversations/grouped")).json()
    assert body["ungrouped"][0]["message_count"] == 2


async def test_update_folder_renames_only(client, make_invite):
    code = await make_invite("INV-F4")
    await register_and_login(client, code, "folderuser4")
    folder_id = (
        await client.post(
            "/v1/folders",
            json={"name": "A", "mode": "local", "local_root_id": _ROOT},
        )
    ).json()["id"]

    r = await client.patch(f"/v1/folders/{folder_id}", json={"name": "B"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "B"
    assert r.json()["mode"] == "local"
    assert r.json()["local_root_id"] == _ROOT

    # Relocate fields are rejected (extra forbid on create; update ignores unknown —
    # binding stays immutable).
    r = await client.patch(
        f"/v1/folders/{folder_id}", json={"local_root_id": "other-root"}
    )
    # Pydantic UpdateFolderRequest has no local_root_id → ignored or 422 depending
    # on extra; either way binding must not change.
    refreshed = (await client.get("/v1/folders")).json()
    match = next(f for f in refreshed if f["id"] == folder_id)
    assert match["local_root_id"] == _ROOT


async def test_delete_folder_archives_conversations(client, make_invite):
    code = await make_invite("INV-F5")
    await register_and_login(client, code, "folderuser5")
    folder_id = await _create_cloud_folder(client, "Temp")
    r = await client.post(
        "/v1/conversations", json={"title": "keep me", "folder_id": folder_id}
    )
    assert r.status_code == 201, r.text
    conv = r.json()["id"]

    r = await client.delete(f"/v1/folders/{folder_id}")
    assert r.status_code == 200, r.text

    body = (await client.get("/v1/conversations/grouped")).json()
    assert body["folders"] == []
    assert body["ungrouped"] == []

    # Conversation survives archived (not ungrouped): live list empty, archived list has it.
    live = (await client.get("/v1/conversations")).json()
    assert live["data"] == []
    archived = (await client.get("/v1/conversations", params={"archived": True})).json()
    assert [c["id"] for c in archived["data"]] == [conv]
    detail = (await client.get(f"/v1/conversations/{conv}")).json()
    assert detail["folder_id"] == folder_id
    assert detail["archived"] is True


async def test_soft_delete_folder_hides_workspace_from_hub(
    client, make_invite, _fs_data_dir
):
    """Soft-deleted ``folder:<id>`` must not appear in list or resolve via locate."""
    code = await make_invite("INV-F-SOFT-WS")
    await register_and_login(client, code, "foldersoftws")
    folder_id = await _create_cloud_folder(client, "SoftGone")
    ws = f"folder:{folder_id}"
    await client.put(f"/v1/workspaces/{ws}/files/keep.txt", content=b"x")

    assert (await client.delete(f"/v1/folders/{folder_id}")).status_code == 200

    listed = (await client.get("/v1/workspaces")).json()["data"]
    assert ws not in {w["ws_id"] for w in listed}
    assert (await client.get(f"/v1/workspaces/{ws}/files")).status_code == 404


async def test_permanent_delete_folder_wipes_conversations_and_cloud_space(
    client, make_invite, session_factory, monkeypatch, _fs_data_dir
):
    """彻底删除: member chats gone, shared cloud files + snapshots purged."""
    monkeypatch.setattr(permanent_delete_mod, "async_session_factory", session_factory)
    code = await make_invite("INV-F7P")
    user_id = await register_and_login(client, code, "folderuser7p")
    folder_id = await _create_cloud_folder(client, "Gone")
    r = await client.post(
        "/v1/conversations", json={"title": "wipe me", "folder_id": folder_id}
    )
    conv = r.json()["id"]
    await _seed_message(session_factory, conv)

    ws = f"folder:{folder_id}"
    assert (
        await client.put(f"/v1/workspaces/{ws}/files/docs/a.txt", content=b"payload")
    ).status_code == 200
    snap = await client.post(f"/v1/workspaces/{ws}/snapshots", json={"label": "pre"})
    assert snap.status_code == 201, snap.text

    r = await client.delete(f"/v1/folders/{folder_id}/permanent")
    assert r.status_code == 200, r.text

    body = (await client.get("/v1/conversations/grouped")).json()
    assert body["folders"] == []
    assert body["ungrouped"] == []
    assert (await client.get(f"/v1/conversations/{conv}")).status_code == 404
    assert (await client.get("/v1/folders")).json() == []
    assert (await client.get(f"/v1/workspaces/{ws}/files")).status_code == 404
    assert not workspace_root_path(
        user_id=user_id, folder_id=folder_id, conversation_id=""
    ).exists()


async def test_permanent_delete_local_folder_keeps_os_sentinel(
    client, make_invite, session_factory, monkeypatch, _fs_data_dir, tmp_path: Path
):
    """Local project wipe clears DB/server data only — never the user's OS directory."""
    monkeypatch.setattr(permanent_delete_mod, "async_session_factory", session_factory)
    # Sentinel stands in for the user's real project directory (desktop root handle
    # is opaque; the server must not rm anything outside data_dir).
    os_sentinel = tmp_path / "user-os-project"
    os_sentinel.mkdir()
    (os_sentinel / "important.txt").write_text("do-not-touch", encoding="utf-8")

    code = await make_invite("INV-F7L")
    await register_and_login(client, code, "folderuser7l")
    r = await client.post(
        "/v1/folders",
        json={
            "name": "LocalGone",
            "mode": "local",
            "local_root_id": _ROOT,
            "local_subpath": "apps",
        },
    )
    assert r.status_code == 201, r.text
    folder_id = r.json()["id"]
    r = await client.post(
        "/v1/conversations", json={"title": "local wipe", "folder_id": folder_id}
    )
    conv = r.json()["id"]

    assert (
        await client.delete(f"/v1/folders/{folder_id}/permanent")
    ).status_code == 200

    assert (await client.get(f"/v1/conversations/{conv}")).status_code == 404
    assert (await client.get("/v1/folders")).json() == []
    assert os_sentinel.exists()
    assert (os_sentinel / "important.txt").read_text(encoding="utf-8") == "do-not-touch"


async def test_folder_isolation_between_users(client, make_invite, new_client):
    code1 = await make_invite("INV-F6A")
    await register_and_login(client, code1, "owneruser")
    folder_id = await _create_cloud_folder(client, "Mine")

    code2 = await make_invite("INV-F6B")
    async with new_client() as other:
        await register_and_login(other, code2, "intruder")

        assert (await other.get("/v1/folders")).json() == []
        assert (
            await other.patch(f"/v1/folders/{folder_id}", json={"name": "x"})
        ).status_code == 404
        assert (await other.delete(f"/v1/folders/{folder_id}")).status_code == 404

        intruder_conv = await _new_conversation(other, "intruder")
        # PATCH folder endpoint is gone for everyone.
        assert (
            await other.patch(
                f"/v1/conversations/{intruder_conv}/folder",
                json={"folder_id": folder_id},
            )
        ).status_code == 404
