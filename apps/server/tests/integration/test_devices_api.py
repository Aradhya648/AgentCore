"""Integration tests for push-device registration (原生推送设备注册, 认证与会话 §十).

Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is reachable.
Covers the auth gate, register→list (token withheld), the idempotent upsert, platform
validation, idempotent logout-unregister, the ownership-MOVE contract on
re-registration (a token belongs to exactly one user), and IDOR isolation.
"""

import httpx

from tests.integration.conftest import register_and_login


async def _register_device(
    client: httpx.AsyncClient, *, token: str, platform: str = "android"
) -> None:
    r = await client.post("/v1/devices", json={"token": token, "platform": platform})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"


async def test_devices_require_auth(client):
    assert (await client.get("/v1/devices")).status_code == 401
    assert (
        await client.post("/v1/devices", json={"token": "t", "platform": "android"})
    ).status_code == 401
    assert (await client.delete("/v1/devices", params={"token": "t"})).status_code == 401


async def test_register_and_list_device(client):
    await register_and_login(client, "deviceuser1")

    await _register_device(client, token="fcm-token-1", platform="android")

    body = (await client.get("/v1/devices")).json()
    assert body["total"] == 1
    device = body["data"][0]
    assert device["platform"] == "android"
    assert device["id"]
    # The raw token is a delivery secret — never echoed back to the client.
    assert "token" not in device


async def test_register_is_idempotent_upsert(client):
    """Re-registering the same token (rotation / re-login) refreshes it in place,
    never duplicating — so a token is owned by exactly one row."""
    await register_and_login(client, "deviceuser2")

    await _register_device(client, token="dup-token", platform="android")
    await _register_device(client, token="dup-token", platform="ios")

    body = (await client.get("/v1/devices")).json()
    assert body["total"] == 1
    # The upsert refreshed the platform in place rather than adding a second row.
    assert body["data"][0]["platform"] == "ios"


async def test_register_rejects_unknown_platform(client):
    await register_and_login(client, "deviceuser3")

    # ``platform`` is a closed set — a bad client can't seed an unroutable row.
    r = await client.post("/v1/devices", json={"token": "t", "platform": "blackberry"})
    assert r.status_code == 422, r.text


async def test_unregister_is_idempotent(client):
    await register_and_login(client, "deviceuser4")
    await _register_device(client, token="bye-token", platform="android")

    # First delete removes it.
    r = await client.delete("/v1/devices", params={"token": "bye-token"})
    assert r.status_code == 200, r.text
    assert (await client.get("/v1/devices")).json()["total"] == 0

    # Deleting an already-gone token still succeeds (the client's goal holds).
    r = await client.delete("/v1/devices", params={"token": "bye-token"})
    assert r.status_code == 200, r.text


async def test_token_moves_to_reregistering_user(client, new_client):
    """A token is owned by exactly one user: the same physical device logging in as
    another account REASSIGNS the token, so a stale owner can never receive the new
    user's pushes (db/repositories/devices.py upsert contract)."""
    await register_and_login(client, "deviceowner")
    await _register_device(client, token="shared-device", platform="android")
    assert (await client.get("/v1/devices")).json()["total"] == 1

    async with new_client() as other:
        await register_and_login(other, "deviceclaimer")
        await _register_device(other, token="shared-device", platform="ios")
        # The token now belongs to B.
        b_body = (await other.get("/v1/devices")).json()
        assert b_body["total"] == 1
        assert b_body["data"][0]["platform"] == "ios"

    # ...and has left A entirely.
    assert (await client.get("/v1/devices")).json()["total"] == 0


async def test_device_isolation_between_users(client, new_client):
    await register_and_login(client, "deviceowner2")
    await _register_device(client, token="owner-token", platform="android")

    async with new_client() as other:
        await register_and_login(other, "intruder2")
        # B sees only its own (empty) device list, never A's.
        assert (await other.get("/v1/devices")).json()["data"] == []
        # B cannot evict A's device — delete is owner-scoped (idempotent ok, no-op).
        r = await other.delete("/v1/devices", params={"token": "owner-token"})
        assert r.status_code == 200, r.text

    # A's device survived the cross-tenant delete attempt.
    assert (await client.get("/v1/devices")).json()["total"] == 1
