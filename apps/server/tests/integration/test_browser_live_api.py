"""Owner-only auth for the M1 team-browser live SSE endpoint (提案 D13).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable. Only the
guard is exercised here (401 unauth, 404 unknown / non-owner) — those reject before any
stream opens, so httpx never hangs. The live fan-out itself is unit-tested in
``tests/test_browser_live.py`` with a fake session (no gVisor / no stream).
"""

import httpx

from tests.integration.conftest import register_and_login


async def _new_conversation(client: httpx.AsyncClient, title: str) -> str:
    r = await client.post("/v1/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_browser_live_requires_auth(client):
    cid = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/v1/conversations/{cid}/browser/live")).status_code == 401


async def test_browser_live_unknown_conversation_is_404(client):
    await register_and_login(client, "bluser1")
    cid = "11111111-1111-1111-1111-111111111111"
    assert (await client.get(f"/v1/conversations/{cid}/browser/live")).status_code == 404


async def test_browser_live_non_owner_is_404(client, new_client):
    await register_and_login(client, "blowner")
    conv = await _new_conversation(client, "mine")

    # IDOR: a different user must not attach to another user's browser live stream.
    async with new_client() as other:
        await register_and_login(other, "blintruder")
        assert (await other.get(f"/v1/conversations/{conv}/browser/live")).status_code == 404
