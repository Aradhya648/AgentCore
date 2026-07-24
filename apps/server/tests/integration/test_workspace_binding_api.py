"""Integration tests for local-mode workspace binding (双模式工作区 §七 / P2d).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Covers the auth gate, the cloud→local→cloud lifecycle on **conversation scratch**
(Folder 重构 To-Be: binding is per-conversation, never folder-scoped / no promote),
the derived mode surfaced on reads, validation, and IDOR isolation.
"""

import httpx

from tests.integration.conftest import register_and_login

_ROOT = "11111111-2222-3333-4444-555555555555"


async def _new_conversation(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_binding_requires_auth(client):
    cid = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/v1/conversations/{cid}/workspace/binding")).status_code == 401
    assert (
        await client.put(f"/v1/conversations/{cid}/workspace/binding", json={"root_id": _ROOT})
    ).status_code == 401
    assert (await client.delete(f"/v1/conversations/{cid}/workspace/binding")).status_code == 401


async def test_bind_conversation_scratch(client, make_invite):
    code = await make_invite("INV-B1")
    await register_and_login(client, code, "binduser1")
    conv = await _new_conversation(client, "solo")

    r = await client.get(f"/v1/conversations/{conv}/workspace/binding")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "mode": "cloud",
        "scope": "conversation",
        "root_id": None,
        "source": None,
    }

    r = await client.put(f"/v1/conversations/{conv}/workspace/binding", json={"root_id": _ROOT})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "mode": "local",
        "scope": "conversation",
        "root_id": _ROOT,
        "source": "explicit",
    }

    detail = (await client.get(f"/v1/conversations/{conv}")).json()
    assert detail["folder_id"] is None
    assert (await client.get(f"/v1/conversations/{conv}/workspace/binding")).json()[
        "mode"
    ] == "local"

    r = await client.delete(f"/v1/conversations/{conv}/workspace/binding")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "mode": "cloud",
        "scope": "conversation",
        "root_id": None,
        "source": None,
    }


async def test_project_chat_inherits_binding_and_rejects_rebind(client, make_invite):
    """Project chats inherit the project's workspace; conversation bind returns 409."""
    code = await make_invite("INV-B2")
    await register_and_login(client, code, "binduser2")
    folder = (
        await client.post(
            "/v1/folders",
            json={"name": "Proj", "mode": "local", "local_root_id": _ROOT},
        )
    ).json()
    folder_id = folder["id"]
    conv_a = (
        await client.post(
            "/v1/conversations", json={"title": "a", "folder_id": folder_id}
        )
    ).json()["id"]
    conv_b = (
        await client.post(
            "/v1/conversations", json={"title": "b", "folder_id": folder_id}
        )
    ).json()["id"]

    for cid in (conv_a, conv_b):
        r = await client.get(f"/v1/conversations/{cid}/workspace/binding")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "mode": "local",
            "scope": "folder",
            "root_id": _ROOT,
            "source": "explicit",
        }

    r = await client.put(
        f"/v1/conversations/{conv_a}/workspace/binding", json={"root_id": "other"}
    )
    assert r.status_code == 409, r.text

    grouped = (await client.get("/v1/conversations/grouped")).json()
    assert grouped["folders"][0]["local_root_id"] == _ROOT
    assert grouped["folders"][0]["mode"] == "local"


async def test_bind_rejects_empty_root_id(client, make_invite):
    code = await make_invite("INV-B3")
    await register_and_login(client, code, "binduser3")
    conv = await _new_conversation(client, "c")
    r = await client.put(f"/v1/conversations/{conv}/workspace/binding", json={"root_id": ""})
    assert r.status_code == 422, r.text


async def test_binding_isolation_between_users(client, make_invite, new_client):
    code1 = await make_invite("INV-B4A")
    await register_and_login(client, code1, "bindowner")
    conv = await _new_conversation(client, "mine")

    code2 = await make_invite("INV-B4B")
    async with new_client() as other:
        await register_and_login(other, code2, "bindintruder")
        assert (await other.get(f"/v1/conversations/{conv}/workspace/binding")).status_code == 404
        assert (
            await other.put(f"/v1/conversations/{conv}/workspace/binding", json={"root_id": _ROOT})
        ).status_code == 404
        assert (
            await other.delete(f"/v1/conversations/{conv}/workspace/binding")
        ).status_code == 404

    assert (await client.get(f"/v1/conversations/{conv}/workspace/binding")).json()[
        "mode"
    ] == "cloud"
