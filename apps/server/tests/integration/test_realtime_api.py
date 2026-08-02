"""Integration tests for the 消息 page realtime fan-out (消息IM.md §四).

Verifies the wiring unit tests can't: a real HTTP send through the messages API
resolves the DI publisher to the *same* process-wide hub the ``/v1/realtime``
route subscribes against, and the message fans out to the recipient's live
connection. Auto-skips (via the shared ``client`` fixture) when no PostgreSQL is
reachable.

The SSE transport itself (the ``/v1/realtime`` generator: ready frame, event
serialization, heartbeat, unsubscribe-on-disconnect) is covered by the unit tests
in ``tests/test_messaging_hub.py`` — httpx's ASGITransport buffers the whole
response body, so it cannot consume an unbounded firehose stream, hence we attach
to the hub directly here rather than reading the SSE endpoint over HTTP.
"""

import asyncio

import httpx

from agentcore.messaging.hub import default_chat_hub
from tests.integration.conftest import register_and_login


async def _user_id(client: httpx.AsyncClient) -> str:
    r = await client.get("/v1/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_realtime_requires_auth(client):
    assert (await client.get("/v1/realtime")).status_code == 401


async def test_send_fans_out_to_recipient(client, new_client):
    """Bob's HTTP send reaches Alice's live hub connection as a chat_message."""
    await register_and_login(client, "rt_alice")
    alice_id = await _user_id(client)

    async with new_client() as bob:
        await register_and_login(bob, "rt_bob")

        r = await bob.post("/v1/messages/chats/dm", json={"user_id": alice_id})
        assert r.status_code == 201, r.text
        chat_id = r.json()["id"]

        # Subscribe to the same process-wide hub the firehose route uses; the DI
        # publisher must resolve here too.
        hub = default_chat_hub()
        sub = hub.subscribe(alice_id)
        try:
            r = await bob.post(
                f"/v1/messages/chats/{chat_id}/messages",
                json={"content": "hello alice"},
            )
            assert r.status_code == 201, r.text
            sent_id = r.json()["id"]

            event = await asyncio.wait_for(sub.get(), timeout=5.0)
        finally:
            hub.unsubscribe(sub)

    assert event["type"] == "chat_message"
    assert event["chat_id"] == chat_id
    assert event["message"]["id"] == sent_id
    assert event["message"]["content"] == "hello alice"
    assert event["message"]["sender_user_id"] != alice_id


async def test_sender_also_receives_for_multidevice(client, new_client):
    """The sender is in the fan-out too (multi-device echo)."""
    await register_and_login(client, "rt_alice_m")
    alice_id = await _user_id(client)

    async with new_client() as bob:
        await register_and_login(bob, "rt_bob_m")
        bob_id = await _user_id(bob)

        r = await bob.post("/v1/messages/chats/dm", json={"user_id": alice_id})
        chat_id = r.json()["id"]

        hub = default_chat_hub()
        sub = hub.subscribe(bob_id)  # Bob's own other device
        try:
            r = await bob.post(
                f"/v1/messages/chats/{chat_id}/messages",
                json={"content": "from bob"},
            )
            assert r.status_code == 201, r.text
            event = await asyncio.wait_for(sub.get(), timeout=5.0)
        finally:
            hub.unsubscribe(sub)

    assert event["chat_id"] == chat_id
    assert event["message"]["content"] == "from bob"


async def test_non_member_not_in_fanout(client, new_client):
    """A user not in the chat is never a fan-out recipient."""
    await register_and_login(client, "rt_alice_l")
    alice_id = await _user_id(client)

    async with new_client() as bob, new_client() as carol:
        await register_and_login(bob, "rt_bob_l")
        await register_and_login(carol, "rt_carol_l")
        carol_id = await _user_id(carol)

        r = await bob.post("/v1/messages/chats/dm", json={"user_id": alice_id})
        chat_id = r.json()["id"]

        # Carol (not a member) listens; she must receive nothing.
        hub = default_chat_hub()
        sub = hub.subscribe(carol_id)
        try:
            r = await bob.post(
                f"/v1/messages/chats/{chat_id}/messages",
                json={"content": "private"},
            )
            assert r.status_code == 201, r.text
            try:
                await asyncio.wait_for(sub.get(), timeout=1.0)
                raise AssertionError("non-member received a fan-out event")
            except TimeoutError:
                pass
        finally:
            hub.unsubscribe(sub)


async def test_rest_online_and_presence_to_co_member(
    client, new_client, session_factory, monkeypatch
):
    """REST peer.online tracks hub; presence fans to users sharing a chat."""
    import agentcore.messaging.presence as presence_mod
    from agentcore.messaging.presence import broadcast_presence, presence_event

    # Presence opens a short-lived session via async_session_factory; point it at
    # the per-test schema (get_db override alone does not cover that path).
    monkeypatch.setattr(presence_mod, "async_session_factory", session_factory)

    await register_and_login(client, "pr_alice")
    alice_id = await _user_id(client)

    async with new_client() as bob:
        await register_and_login(bob, "pr_bob")
        bob_id = await _user_id(bob)

        r = await bob.post("/v1/messages/chats/dm", json={"user_id": alice_id})
        assert r.status_code == 201, r.text
        chat_id = r.json()["id"]

        chats = (await client.get("/v1/messages/chats")).json()["data"]
        dm = next(c for c in chats if c["id"] == chat_id)
        assert dm["peer"]["id"] == bob_id
        assert dm["peer"]["online"] is False

        hub = default_chat_hub()
        bob_sub = hub.subscribe(bob_id)
        try:
            chats = (await client.get("/v1/messages/chats")).json()["data"]
            dm = next(c for c in chats if c["id"] == chat_id)
            assert dm["peer"]["online"] is True

            alice_sub = hub.subscribe(alice_id)
            try:
                await broadcast_presence(bob_id, online=False, hub=hub)
                event = await asyncio.wait_for(alice_sub.get(), timeout=5.0)
                assert event == presence_event(user_id=bob_id, online=False)
            finally:
                hub.unsubscribe(alice_sub)
        finally:
            hub.unsubscribe(bob_sub)

        chats = (await client.get("/v1/messages/chats")).json()["data"]
        dm = next(c for c in chats if c["id"] == chat_id)
        assert dm["peer"]["online"] is False
