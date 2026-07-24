"""Integration tests for global search (全局搜索 Tier 1, GET /v1/search).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
The pure helpers (snippet windowing, ``types`` parsing, ILIKE escaping) are unit-
tested in ``test_search.py``; this exercises the end-to-end DB-backed route: the
auth gate, the fan-out over conversations/messages/folders, per-section ``limit``,
the ``types`` filter, omission of empty sections, message snippet highlight
offsets, and owner-scoping (a non-owner's data never appears — IDOR-safe).
"""

import httpx

from agentcore.db.repositories import MessageRepository
from tests.integration.conftest import register_and_login


async def _new_conversation(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _seed_message(session_factory, conversation_id: str, content: str) -> None:
    async with session_factory() as session:
        await MessageRepository(session).create(
            conversation_id=conversation_id, role="user", content=content
        )


def _sections(body: dict) -> dict[str, list]:
    return {s["type"]: s["items"] for s in body["sections"]}


async def test_search_requires_auth(client):
    assert (await client.get("/v1/search", params={"q": "hello"})).status_code == 401


async def test_search_requires_query(client, make_invite):
    code = await make_invite("INV-SR-Q")
    await register_and_login(client, code, "searchuser_q")
    # ``q`` is required (min_length=1) — a logged-in caller with no query is a 422.
    assert (await client.get("/v1/search")).status_code == 422


async def test_search_fans_out_over_all_entity_types(client, make_invite, session_factory):
    code = await make_invite("INV-SR-1")
    await register_and_login(client, code, "searchuser1")

    conv = await _new_conversation(client, "Deploy checklist")
    await _seed_message(session_factory, conv, "remember to deploy on friday")
    await client.post("/v1/folders", json={"name": "Deploy notes", "mode": "cloud"})

    body = (await client.get("/v1/search", params={"q": "deploy"})).json()
    assert body["query"] == "deploy"
    sections = _sections(body)
    assert set(sections) == {"conversation", "message", "folder"}
    assert sections["conversation"][0]["title"] == "Deploy checklist"
    assert sections["folder"][0]["title"] == "Deploy notes"
    msg_hit = sections["message"][0]
    assert msg_hit["conversation_id"] == conv
    assert msg_hit["role"] == "user"


async def test_search_message_snippet_carries_highlight_offsets(
    client, make_invite, session_factory
):
    code = await make_invite("INV-SR-2")
    await register_and_login(client, code, "searchuser2")
    conv = await _new_conversation(client, "ctx")
    await _seed_message(session_factory, conv, "the DEPLOYMENT pipeline needs review")

    body = (
        await client.get("/v1/search", params={"q": "deployment", "types": "message"})
    ).json()
    hit = _sections(body)["message"][0]
    assert hit["snippet"]
    assert hit["match_start"] is not None and hit["match_end"] is not None
    # Offsets index into the returned snippet and preserve the original casing.
    assert hit["snippet"][hit["match_start"] : hit["match_end"]] == "DEPLOYMENT"


async def test_search_types_filter_narrows_sections(client, make_invite, session_factory):
    code = await make_invite("INV-SR-3")
    await register_and_login(client, code, "searchuser3")
    conv = await _new_conversation(client, "alpha conversation")
    await _seed_message(session_factory, conv, "alpha message body")
    await client.post("/v1/folders", json={"name": "alpha folder", "mode": "cloud"})

    body = (await client.get("/v1/search", params={"q": "alpha", "types": "folder"})).json()
    sections = _sections(body)
    assert set(sections) == {"folder"}
    assert sections["folder"][0]["title"] == "alpha folder"


async def test_search_omits_empty_sections(client, make_invite):
    code = await make_invite("INV-SR-4")
    await register_and_login(client, code, "searchuser4")
    await _new_conversation(client, "nothing relevant here")

    body = (await client.get("/v1/search", params={"q": "zzz-no-such-term"})).json()
    assert body["sections"] == []


async def test_search_limit_caps_each_section(client, make_invite):
    code = await make_invite("INV-SR-5")
    await register_and_login(client, code, "searchuser5")
    for i in range(3):
        await _new_conversation(client, f"capme {i}")

    body = (await client.get("/v1/search", params={"q": "capme", "limit": 2})).json()
    assert len(_sections(body)["conversation"]) == 2


async def test_search_folder_id_scopes_to_workspace(client, make_invite, session_factory):
    """``folder_id`` (工作区过滤) keeps only in-folder conversation/message hits and
    drops the folder section (searching *inside* a workspace, not *for* a folder)."""
    code = await make_invite("INV-SR-7")
    await register_and_login(client, code, "searchuser7")

    folder = (await client.post("/v1/folders", json={"name": "scoped ws", "mode": "cloud"})).json()["id"]
    inside = (
        await client.post(
            "/v1/conversations", json={"title": "scoped alpha", "folder_id": folder}
        )
    ).json()["id"]
    await _seed_message(session_factory, inside, "scoped alpha body")
    outside = await _new_conversation(client, "scoped alpha outside")
    await _seed_message(session_factory, outside, "scoped alpha body outside")

    body = (
        await client.get("/v1/search", params={"q": "scoped alpha", "folder_id": folder})
    ).json()
    sections = _sections(body)
    # Folder section is dropped under a workspace scope.
    assert "folder" not in sections
    # Only the in-folder conversation + its message survive the scope.
    assert {i["id"] for i in sections.get("conversation", [])} == {inside}
    assert {i["conversation_id"] for i in sections.get("message", [])} == {inside}


async def test_search_updated_after_filters_by_time(client, make_invite):
    """``updated_after`` (时间过滤) bounds results to recent activity."""
    code = await make_invite("INV-SR-8")
    await register_and_login(client, code, "searchuser8")
    await _new_conversation(client, "timed alpha")

    # A far-future bound excludes the just-created row entirely.
    future = (
        await client.get(
            "/v1/search",
            params={"q": "timed alpha", "updated_after": "2999-01-01T00:00:00Z"},
        )
    ).json()
    assert future["sections"] == []

    # A far-past bound keeps it.
    past = (
        await client.get(
            "/v1/search",
            params={"q": "timed alpha", "updated_after": "2000-01-01T00:00:00Z"},
        )
    ).json()
    assert "conversation" in _sections(past)


async def test_search_is_owner_scoped(client, make_invite, new_client, session_factory):
    """A user's search never surfaces another user's conversations/messages/folders."""
    code_a = await make_invite("INV-SR-6A")
    await register_and_login(client, code_a, "searchowner")
    conv = await _new_conversation(client, "confidential roadmap")
    await _seed_message(session_factory, conv, "confidential launch date")
    await client.post("/v1/folders", json={"name": "confidential folder", "mode": "cloud"})

    code_b = await make_invite("INV-SR-6B")
    async with new_client() as other:
        await register_and_login(other, code_b, "searchintruder")
        # Intruder querying the owner's keyword gets nothing.
        body = (await other.get("/v1/search", params={"q": "confidential"})).json()
        assert body["sections"] == []

    # The owner still finds all three.
    body = (await client.get("/v1/search", params={"q": "confidential"})).json()
    assert set(_sections(body)) == {"conversation", "message", "folder"}
