"""Owner-only auth + precondition semantics for the M2 team-browser takeover endpoints (D16/D17).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable. Exercises the
guards (401 unauth, 404 unknown / non-owner) plus the no-gVisor precondition surface: start
reports ``no_session`` (no live sandbox in a test process), input is 409 unless takeover is
active, and the audit list starts empty. The takeover state machine + 留档 paths are
unit-tested in ``tests/test_browser_takeover.py`` (fake session + fake store, no gVisor / DB).
"""

import httpx

from tests.integration.conftest import register_and_login


async def _new_conversation(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_takeover_endpoints_require_auth(client):
    cid = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.post(f"/v1/conversations/{cid}/browser/takeover", json={"action": "start"})
    ).status_code == 401
    assert (
        await client.post(f"/v1/conversations/{cid}/browser/input", json={"events": []})
    ).status_code == 401
    assert (await client.get(f"/v1/conversations/{cid}/browser/takeovers")).status_code == 401


async def test_takeover_unknown_conversation_is_404(client, make_invite):
    code = await make_invite("INV-BT1")
    await register_and_login(client, code, "btuser1")
    cid = "11111111-1111-1111-1111-111111111111"
    assert (
        await client.post(f"/v1/conversations/{cid}/browser/takeover", json={"action": "start"})
    ).status_code == 404
    assert (await client.get(f"/v1/conversations/{cid}/browser/takeovers")).status_code == 404


async def test_takeover_non_owner_is_404(client, make_invite, new_client):
    code = await make_invite("INV-BT2")
    await register_and_login(client, code, "btowner")
    conv = await _new_conversation(client, "mine")

    # IDOR: a different user must not start/list a takeover on another user's conversation.
    code2 = await make_invite("INV-BT3")
    async with new_client() as other:
        await register_and_login(other, code2, "btintruder")
        assert (
            await other.post(
                f"/v1/conversations/{conv}/browser/takeover", json={"action": "start"}
            )
        ).status_code == 404
        assert (
            await other.get(f"/v1/conversations/{conv}/browser/takeovers")
        ).status_code == 404


async def test_start_without_session_reports_no_session(client, make_invite):
    code = await make_invite("INV-BT4")
    await register_and_login(client, code, "btuser4")
    conv = await _new_conversation(client, "no-browser")
    r = await client.post(
        f"/v1/conversations/{conv}/browser/takeover", json={"action": "start"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is False and body["reason"] == "no_session"


async def test_input_conflict_when_not_active(client, make_invite):
    code = await make_invite("INV-BT5")
    await register_and_login(client, code, "btuser5")
    conv = await _new_conversation(client, "no-takeover")
    r = await client.post(f"/v1/conversations/{conv}/browser/input", json={"events": []})
    assert r.status_code == 409, r.text


async def test_end_is_idempotent_when_not_active(client, make_invite):
    code = await make_invite("INV-BT6")
    await register_and_login(client, code, "btuser6")
    conv = await _new_conversation(client, "no-takeover2")
    r = await client.post(f"/v1/conversations/{conv}/browser/takeover", json={"action": "end"})
    assert r.status_code == 200, r.text
    assert r.json()["reason"] == "not_active"


async def test_takeovers_list_starts_empty(client, make_invite):
    code = await make_invite("INV-BT7")
    await register_and_login(client, code, "btuser7")
    conv = await _new_conversation(client, "empty-list")
    r = await client.get(f"/v1/conversations/{conv}/browser/takeovers")
    assert r.status_code == 200, r.text
    assert r.json() == {"data": []}
