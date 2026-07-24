"""Integration tests for message bookmarks (消息收藏, /v1/bookmarks).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Exercises the end-to-end DB-backed routes: create (idempotent), the「已收藏」list
(cross-device view), the per-conversation star-state ids, remove, owner-scoping
(IDOR — a non-owner can neither bookmark nor read another account's data), and the
list join dropping a soft-deleted conversation's bookmarks.
"""

import httpx

from agentcore.db.repositories import MessageRepository
from tests.integration.conftest import register_and_login


async def _new_conversation(client: httpx.AsyncClient, title: str = "ctx") -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_message_id(
    session_factory, conversation_id: str, content: str, role: str = "assistant"
) -> str:
    async with session_factory() as session:
        msg = await MessageRepository(session).create(
            conversation_id=conversation_id, role=role, content=content
        )
    return msg.id


async def test_bookmark_requires_auth(client):
    r = await client.post(
        "/v1/bookmarks", json={"conversation_id": "x", "message_id": "y"}
    )
    assert r.status_code == 401


async def test_create_list_and_ids(client, make_invite, session_factory):
    code = await make_invite("INV-BM-1")
    await register_and_login(client, code, "bmuser1")
    conv = await _new_conversation(client, "bm conv")
    mid = await _seed_message_id(session_factory, conv, "an important assistant reply")

    r = await client.post(
        "/v1/bookmarks", json={"conversation_id": conv, "message_id": mid}
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["message_id"] == mid
    assert item["conversation_id"] == conv
    assert item["conversation_title"] == "bm conv"
    assert item["role"] == "assistant"
    assert "important assistant reply" in (item["snippet"] or "")

    # The「已收藏」cross-device list carries the same hit.
    data = (await client.get("/v1/bookmarks")).json()["data"]
    assert [b["message_id"] for b in data] == [mid]

    # Per-conversation star state.
    ids = (
        await client.get("/v1/bookmarks/ids", params={"conversation_id": conv})
    ).json()["message_ids"]
    assert ids == [mid]


async def test_bookmark_is_idempotent(client, make_invite, session_factory):
    code = await make_invite("INV-BM-2")
    await register_and_login(client, code, "bmuser2")
    conv = await _new_conversation(client)
    mid = await _seed_message_id(session_factory, conv, "dup me")

    r1 = await client.post(
        "/v1/bookmarks", json={"conversation_id": conv, "message_id": mid}
    )
    r2 = await client.post(
        "/v1/bookmarks", json={"conversation_id": conv, "message_id": mid}
    )
    assert r1.status_code == 201 and r2.status_code == 201
    # Same bookmark row both times — no duplicate.
    assert r1.json()["id"] == r2.json()["id"]
    assert len((await client.get("/v1/bookmarks")).json()["data"]) == 1


async def test_remove_bookmark_is_idempotent(client, make_invite, session_factory):
    code = await make_invite("INV-BM-3")
    await register_and_login(client, code, "bmuser3")
    conv = await _new_conversation(client)
    mid = await _seed_message_id(session_factory, conv, "remove me")
    await client.post("/v1/bookmarks", json={"conversation_id": conv, "message_id": mid})

    assert (await client.delete(f"/v1/bookmarks/{mid}")).status_code == 200
    assert (await client.get("/v1/bookmarks")).json()["data"] == []
    # Removing an already-gone bookmark is still a clean 200.
    assert (await client.delete(f"/v1/bookmarks/{mid}")).status_code == 200


async def test_bookmark_is_owner_scoped(client, make_invite, new_client, session_factory):
    """A non-owner can neither bookmark another user's message nor read their data."""
    code_a = await make_invite("INV-BM-4A")
    await register_and_login(client, code_a, "bmowner")
    conv = await _new_conversation(client, "owner conv")
    mid = await _seed_message_id(session_factory, conv, "owner secret")
    await client.post("/v1/bookmarks", json={"conversation_id": conv, "message_id": mid})

    code_b = await make_invite("INV-BM-4B")
    async with new_client() as other:
        await register_and_login(other, code_b, "bmintruder")
        # Cannot bookmark a message in a conversation they don't own.
        r = await other.post(
            "/v1/bookmarks", json={"conversation_id": conv, "message_id": mid}
        )
        assert r.status_code == 404
        # Cannot read star-state for another user's conversation.
        assert (
            await other.get("/v1/bookmarks/ids", params={"conversation_id": conv})
        ).status_code == 404
        # Their own list never surfaces the owner's bookmark.
        assert (await other.get("/v1/bookmarks")).json()["data"] == []


async def test_bookmark_missing_message_404(client, make_invite):
    code = await make_invite("INV-BM-5")
    await register_and_login(client, code, "bmuser5")
    conv = await _new_conversation(client)
    r = await client.post(
        "/v1/bookmarks",
        json={
            "conversation_id": conv,
            "message_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert r.status_code == 404


async def test_soft_deleted_conversation_hides_bookmarks(
    client, make_invite, session_factory
):
    code = await make_invite("INV-BM-6")
    await register_and_login(client, code, "bmuser6")
    conv = await _new_conversation(client, "to delete")
    mid = await _seed_message_id(session_factory, conv, "will vanish from 已收藏")
    await client.post("/v1/bookmarks", json={"conversation_id": conv, "message_id": mid})
    assert len((await client.get("/v1/bookmarks")).json()["data"]) == 1

    # Soft-deleting the conversation drops its bookmarks from the list (join filter).
    assert (await client.delete(f"/v1/conversations/{conv}")).status_code == 200
    assert (await client.get("/v1/bookmarks")).json()["data"] == []
