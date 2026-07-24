"""Unit tests for the realtime fan-out hub + firehose (消息IM.md §四).

Covers the in-process pub/sub used to deliver chat messages to online recipients'
SSE firehoses: per-user fan-out, multi-device delivery, no cross-user leak,
unsubscribe cleanup, bounded-queue backpressure (drop oldest), the
``HubChatEventPublisher`` seam, and the SSE generator's ready/heartbeat/teardown
behaviour. No DB, no HTTP — plain async tests (asyncio_mode=auto).
"""

import asyncio

from agentcore.api.routes.realtime import _firehose, _format_event
from agentcore.messaging.hub import (
    _SUBSCRIBER_QUEUE_MAXSIZE,
    ChatHub,
    HubChatEventPublisher,
    Subscription,
    default_chat_hub,
)


async def test_publish_delivers_to_subscriber():
    hub = ChatHub()
    sub = hub.subscribe("u1")
    await hub.publish(["u1"], {"type": "chat_message", "chat_id": "c1"})
    event = await sub.get()
    assert event == {"type": "chat_message", "chat_id": "c1"}


async def test_publish_fans_out_to_all_user_connections():
    """A user on two devices: every connection receives the event."""
    hub = ChatHub()
    sub_a = hub.subscribe("u1")
    sub_b = hub.subscribe("u1")
    assert hub.connection_count("u1") == 2

    await hub.publish(["u1"], {"type": "chat_message"})

    assert (await sub_a.get())["type"] == "chat_message"
    assert (await sub_b.get())["type"] == "chat_message"


async def test_publish_does_not_leak_across_users():
    hub = ChatHub()
    sub_a = hub.subscribe("u1")
    sub_b = hub.subscribe("u2")

    await hub.publish(["u1"], {"type": "secret"})

    assert (await sub_a.get())["type"] == "secret"
    # u2 must not see u1's event.
    try:
        await asyncio.wait_for(sub_b.get(), timeout=0.05)
        raise AssertionError("u2 should not receive u1's event")
    except TimeoutError:
        pass


async def test_publish_dedups_repeated_user_ids():
    """Duplicate ids in one publish deliver exactly once per connection."""
    hub = ChatHub()
    sub = hub.subscribe("u1")

    await hub.publish(["u1", "u1", "u1"], {"type": "once"})

    assert (await sub.get())["type"] == "once"
    try:
        await asyncio.wait_for(sub.get(), timeout=0.05)
        raise AssertionError("event should have been delivered only once")
    except TimeoutError:
        pass


async def test_unsubscribe_stops_delivery_and_cleans_up():
    hub = ChatHub()
    sub = hub.subscribe("u1")
    assert hub.connection_count("u1") == 1

    hub.unsubscribe(sub)
    assert hub.connection_count("u1") == 0

    # No connection left → publish is a no-op (and must not raise).
    await hub.publish(["u1"], {"type": "chat_message"})


async def test_unsubscribe_keeps_other_connections():
    hub = ChatHub()
    sub_a = hub.subscribe("u1")
    sub_b = hub.subscribe("u1")

    hub.unsubscribe(sub_a)
    assert hub.connection_count("u1") == 1

    await hub.publish(["u1"], {"type": "still-here"})
    assert (await sub_b.get())["type"] == "still-here"


async def test_unsubscribe_is_idempotent():
    hub = ChatHub()
    sub = hub.subscribe("u1")
    hub.unsubscribe(sub)
    hub.unsubscribe(sub)  # must not raise
    assert hub.connection_count("u1") == 0


async def test_backpressure_drops_oldest_when_full():
    """A stalled connection sheds its oldest undelivered events, never blocks."""
    hub = ChatHub()
    sub = hub.subscribe("u1")

    total = _SUBSCRIBER_QUEUE_MAXSIZE + 1
    for i in range(total):
        await hub.publish(["u1"], {"type": "m", "i": i})

    # Queue holds the most recent maxsize events; index 0 was dropped.
    drained = [await sub.get() for _ in range(_SUBSCRIBER_QUEUE_MAXSIZE)]
    assert drained[0] == {"type": "m", "i": 1}
    assert drained[-1] == {"type": "m", "i": total - 1}


async def test_subscription_offer_reports_drop():
    sub = Subscription("u1")
    for i in range(_SUBSCRIBER_QUEUE_MAXSIZE):
        assert sub._offer({"i": i}) is True
    # The next offer overflows and must report the drop.
    assert sub._offer({"i": _SUBSCRIBER_QUEUE_MAXSIZE}) is False


async def test_close_ends_async_iteration():
    sub = Subscription("u1")
    await sub._queue.put({"type": "a"})
    sub.close()

    seen = [event async for event in sub]
    # close() drains the backlog before the sentinel, so iteration ends cleanly.
    assert seen == []


async def test_hub_publisher_delegates_to_hub():
    hub = ChatHub()
    sub = hub.subscribe("u1")
    publisher = HubChatEventPublisher(hub)

    await publisher.publish(["u1"], {"type": "chat_message", "chat_id": "c1"})

    assert (await sub.get()) == {"type": "chat_message", "chat_id": "c1"}


async def test_default_chat_hub_is_singleton():
    assert default_chat_hub() is default_chat_hub()


# --- SSE firehose generator (route helper) ---


def test_format_event_is_named_sse_frame():
    frame = _format_event({"type": "chat_message", "chat_id": "c1"})
    assert frame.startswith("event: chat_message\n")
    assert '"chat_id": "c1"' in frame
    assert frame.endswith("\n\n")


def test_format_event_defaults_type():
    assert _format_event({"foo": "bar"}).startswith("event: message\n")


async def test_firehose_streams_ready_then_event_and_unsubscribes():
    hub = ChatHub()
    sub = hub.subscribe("u1")
    gen = _firehose(sub, hub)

    first = await gen.__anext__()
    assert first.startswith("event: ready\n")

    await hub.publish(["u1"], {"type": "chat_message", "chat_id": "c1"})
    second = await gen.__anext__()
    assert second.startswith("event: chat_message\n")
    assert '"chat_id": "c1"' in second

    # Client disconnect → generator close → unsubscribe runs in finally.
    await gen.aclose()
    assert hub.connection_count("u1") == 0


async def test_firehose_stops_on_sentinel():
    hub = ChatHub()
    sub = hub.subscribe("u1")
    gen = _firehose(sub, hub)

    assert (await gen.__anext__()).startswith("event: ready\n")

    sub.close()  # hub-initiated close delivers the None sentinel
    try:
        await gen.__anext__()
        raise AssertionError("generator should have stopped on the sentinel")
    except StopAsyncIteration:
        pass
    assert hub.connection_count("u1") == 0
