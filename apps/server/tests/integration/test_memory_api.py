"""End-to-end API integration tests for the per-leaf memory surface (Agent记忆与知识系统 §1.6).

Covers the route/DI/serialization chain for ``/v1/users/me/memory/files/{kind}`` and
``/v1/users/me/memory/projects`` against a real PG schema: per-leaf CAS round-trip +
conflict, clearing a leaf, project-scoped 画像 isolated from global, the projects
enumeration the「文件」rail uses, the 偏好-is-always-global invariant, and auth gating.

The memory FILES live on disk via ``FileMemoryStore`` under ``settings.data_dir``; an
autouse fixture points that at a per-test ``tmp_path`` so the suite is hermetic and never
touches the real data dir.
"""

import uuid

import pytest

from agentcore.config import settings
from tests.integration.conftest import register_and_login

# Memory now lives in the ``documents`` table (§5.7 换底), so per-test isolation comes from the
# per-test schema (session_factory), not the data dir. A project scope is a workspace ``Folder``
# id — always a UUID in production (``conversations.folder_id``), so tests use a real one here
# (the file store tolerated any string; the ``PG_UUID`` column does not).
_PROJECT_FOLDER_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _isolated_memory_dir(tmp_path, monkeypatch):
    # Legacy data-dir isolation kept harmless for any residual file paths; the DB store binds to
    # the request session (per-test schema), which is what actually isolates memory now.
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


async def test_per_file_roundtrip_and_cas(client):
    await register_and_login(client, "mem1")

    # A brand-new user's 偏好 leaf is empty (with a stable empty-content CAS tag).
    r = await client.get("/v1/users/me/memory/files/preferences")
    assert r.status_code == 200, r.text
    empty_version = r.json()["version"]
    assert r.json()["content"] == ""

    # Write it (baseline = the empty tag → conflict-free first write).
    body = "## 沟通偏好\n- 用中文\n"
    r = await client.put(
        "/v1/users/me/memory/files/preferences",
        json={"content": body, "baseline": empty_version},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["conflict"] is False
    new_version = r.json()["version"]

    # It reads back.
    r = await client.get("/v1/users/me/memory/files/preferences")
    assert r.json()["content"] == body and r.json()["version"] == new_version

    # A stale baseline (the old empty tag) is rejected as a conflict, not clobbered.
    r = await client.put(
        "/v1/users/me/memory/files/preferences",
        json={"content": "覆盖?", "baseline": empty_version},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and r.json()["conflict"] is True
    # The live content is untouched.
    assert (await client.get("/v1/users/me/memory/files/preferences")).json()["content"] == body

    # Clearing (empty content, unconditional) drops the leaf.
    r = await client.put(
        "/v1/users/me/memory/files/preferences",
        json={"content": "", "baseline": None},
    )
    assert r.json()["ok"] is True
    assert (await client.get("/v1/users/me/memory/files/preferences")).json()["content"] == ""


async def test_project_scope_isolated_and_enumerated(client):
    await register_and_login(client, "mem2")

    await client.put(
        "/v1/users/me/memory/files/profile",
        json={"content": "全局事实", "baseline": None},
    )
    await client.put(
        f"/v1/users/me/memory/files/profile?folder_id={_PROJECT_FOLDER_ID}",
        json={"content": "本项目事实", "baseline": None},
    )

    # Each layer reads its own body; global and project never bleed into each other.
    g = await client.get("/v1/users/me/memory/files/profile")
    p = await client.get(f"/v1/users/me/memory/files/profile?folder_id={_PROJECT_FOLDER_ID}")
    assert g.json()["content"] == "全局事实"
    assert p.json()["content"] == "本项目事实"

    # The rail enumeration surfaces exactly the project that has memory.
    r = await client.get("/v1/users/me/memory/projects")
    assert r.status_code == 200, r.text
    assert r.json()["folders"] == [_PROJECT_FOLDER_ID]


async def test_preferences_folder_id_is_ignored_and_stays_global(client):
    await register_and_login(client, "mem3")

    # Writing preferences WITH a folder_id still lands on the GLOBAL 偏好 (invariant §1.4).
    await client.put(
        f"/v1/users/me/memory/files/preferences?folder_id={_PROJECT_FOLDER_ID}",
        json={"content": "用中文", "baseline": None},
    )
    assert (await client.get("/v1/users/me/memory/files/preferences")).json()["content"] == "用中文"
    # No project layer was created → the rail shows no project node.
    assert (await client.get("/v1/users/me/memory/projects")).json()["folders"] == []


async def test_topics_list_read_write_clear_and_scope(client):
    await register_and_login(client, "mem4")

    # A brand-new user has no topics, and an unknown topic reads empty (stable empty tag).
    assert (await client.get("/v1/users/me/memory/topics")).json()["topics"] == []
    r = await client.get("/v1/users/me/memory/topics/部署流程")
    assert r.status_code == 200, r.text
    empty_version = r.json()["version"]
    assert r.json()["content"] == ""

    # First write (baseline = empty tag) is conflict-free; it then lists + reads back.
    body = "# 部署流程\n- 先构建后推送\n"
    r = await client.put(
        "/v1/users/me/memory/topics/部署流程",
        json={"content": body, "baseline": empty_version},
    )
    assert r.json()["ok"] is True and r.json()["conflict"] is False
    assert (await client.get("/v1/users/me/memory/topics")).json()["topics"] == ["部署流程"]
    assert (await client.get("/v1/users/me/memory/topics/部署流程")).json()["content"] == body

    # A project-scoped topic is isolated from global; each scope lists only its own.
    await client.put(
        f"/v1/users/me/memory/topics/调试配方?folder_id={_PROJECT_FOLDER_ID}",
        json={"content": "本项目调试", "baseline": None},
    )
    assert (await client.get("/v1/users/me/memory/topics")).json()["topics"] == ["部署流程"]
    p = await client.get(f"/v1/users/me/memory/topics?folder_id={_PROJECT_FOLDER_ID}")
    assert p.json()["topics"] == ["调试配方"]
    # Project topics also make the project surface in the rail enumeration.
    assert (await client.get("/v1/users/me/memory/projects")).json()["folders"] == [
        _PROJECT_FOLDER_ID
    ]

    # Clearing (empty body, unconditional) deletes the note → it leaves the directory.
    r = await client.put(
        "/v1/users/me/memory/topics/部署流程",
        json={"content": "", "baseline": None},
    )
    assert r.json()["ok"] is True
    assert (await client.get("/v1/users/me/memory/topics")).json()["topics"] == []


async def test_topic_cas_conflict_is_not_clobbered(client):
    await register_and_login(client, "mem5")

    empty_version = (await client.get("/v1/users/me/memory/topics/笔记")).json()["version"]
    await client.put(
        "/v1/users/me/memory/topics/笔记", json={"content": "v1", "baseline": empty_version}
    )
    # A stale baseline (the old empty tag) is rejected as a conflict, content untouched.
    r = await client.put(
        "/v1/users/me/memory/topics/笔记", json={"content": "v2", "baseline": empty_version}
    )
    assert r.json()["ok"] is False and r.json()["conflict"] is True
    assert (await client.get("/v1/users/me/memory/topics/笔记")).json()["content"] == "v1"


async def test_memory_updates_feed_lists_newest_first_across_conversations(
    client, session_factory
):
    # 记忆动态 feed (记忆编辑器「最近更新」视图): the cross-conversation stream of what the AI
    # recently learned — newest-first, carrying each pass's source conversation + item detail.
    from agentcore.db.repositories import MemoryUpdateRepository, UserRepository

    await register_and_login(client, "mem6")

    async with session_factory() as session:
        user = await UserRepository(session).get_by_username("mem6")
        assert user is not None
        uid = user.user_id

    conv_old = str(uuid.uuid4())
    conv_new = str(uuid.uuid4())
    # Two passes in separate transactions → distinct server now() → deterministic order.
    async with session_factory() as session:
        await MemoryUpdateRepository(session).record(
            conversation_id=conv_old,
            user_id=uid,
            items=[
                {
                    "action": "add",
                    "file": "画像",
                    "section": "关于用户的事实",
                    "scope": "global",
                    "content": "较早记下的事实",
                    "target": "global/profile",
                }
            ],
        )
    async with session_factory() as session:
        await MemoryUpdateRepository(session).record(
            conversation_id=conv_new,
            user_id=uid,
            items=[
                {
                    "action": "update",
                    "file": "偏好",
                    "section": "",
                    "scope": "global",
                    "content": "较新的偏好",
                    "target": "global/preferences",
                }
            ],
        )

    r = await client.get("/v1/users/me/memory/updates")
    assert r.status_code == 200, r.text
    updates = r.json()["updates"]
    assert len(updates) == 2
    # Newest-first, each carrying its own source conversation.
    assert updates[0]["conversation_id"] == conv_new
    assert updates[1]["conversation_id"] == conv_old
    # Item detail (with the leaf deep-link target) round-trips for the feed rows.
    assert updates[0]["items"][0]["content"] == "较新的偏好"
    assert updates[0]["items"][0]["target"] == "global/preferences"
    assert updates[1]["items"][0]["file"] == "画像"


async def test_memory_updates_feed_isolated_per_user(
    client, new_client, session_factory
):
    # One user's memory activity must never leak into another's feed (private per-user data).
    from agentcore.db.repositories import MemoryUpdateRepository, UserRepository

    await register_and_login(client, "mem7a")
    async with session_factory() as session:
        owner = await UserRepository(session).get_by_username("mem7a")
        assert owner is not None
    async with session_factory() as session:
        await MemoryUpdateRepository(session).record(
            conversation_id=str(uuid.uuid4()),
            user_id=owner.user_id,
            items=[{"action": "add", "file": "画像", "scope": "global", "content": "私密"}],
        )

    # A different user sees an empty feed — the row is scoped to its owner.
    async with new_client() as other:
        await register_and_login(other, "mem7b")
        r = await other.get("/v1/users/me/memory/updates")
        assert r.status_code == 200, r.text
        assert r.json()["updates"] == []


async def test_memory_files_require_auth(client):
    assert (await client.get("/v1/users/me/memory/files/profile")).status_code == 401
    assert (await client.get("/v1/users/me/memory/projects")).status_code == 401
    assert (await client.get("/v1/users/me/memory/topics")).status_code == 401
    assert (await client.get("/v1/users/me/memory/updates")).status_code == 401
