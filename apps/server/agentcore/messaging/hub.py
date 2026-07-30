"""In-process realtime pub/sub for the 消息 page firehose (消息IM.md §四).

Single-worker fan-out: ``MessagingService`` persists a chat message, then publishes
it here, and the hub pushes it to every online recipient's SSE firehose
(``GET /v1/realtime``). State is in-process — the same single-worker posture the
rate limiter and approval registry already take; front with Redis / NATS pub-sub
to scale to multiple workers (§五, §八), behind the ``ChatEventPublisher`` seam.

A user may hold several live connections (multi-device): a publish fans the event
into every one. Each connection's queue is bounded — a connection too slow to
drain sheds its oldest undelivered events rather than growing without bound or
stalling the publisher; the client re-syncs anything it missed on reconnect via
the chat's ``last_read_message_id`` (离线补偿, §五), so a drop is recoverable, not
a lost message.

Presence (online = ≥1 live subscription) is read from this hub; connect/disconnect
transitions fan ``presence`` events to co-chat users via
:mod:`agentcore.messaging.presence` (not stored).
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence
from typing import Any

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# A stalled connection's queue is capped here; once full, the oldest undelivered
# event is dropped to make room. Sized generously so only a genuinely stuck client
# sheds, while reconnect catch-up keeps a drop from losing data.
_SUBSCRIBER_QUEUE_MAXSIZE = 1000


class Subscription:
    """One live firehose connection's event queue, registered in the hub.

    Drive it from the SSE route via :meth:`get` (or by async iteration); it ends
    when the hub delivers the ``None`` sentinel (:meth:`close`). On client
    disconnect the route unsubscribes it from the hub.
    """

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
            maxsize=_SUBSCRIBER_QUEUE_MAXSIZE
        )

    def _offer(self, event: dict[str, Any]) -> bool:
        """Enqueue ``event`` for this connection; drop the oldest when full.

        Returns ``False`` when an undelivered event had to be shed to make room
        (best-effort delivery), so the hub can log the backpressure. A stalled
        consumer must never block the publisher or its peers.
        """
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(event)
            return False

    def close(self) -> None:
        """Signal end-of-stream to the consumer (drains backlog, then sentinel)."""
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._queue.put_nowait(None)

    async def get(self) -> dict[str, Any] | None:
        """Await the next event, or ``None`` once the stream is closed."""
        return await self._queue.get()

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event


class ChatHub:
    """Process-wide in-memory pub/sub fanning chat events to live firehoses."""

    def __init__(self) -> None:
        # user_id → that user's live connections (a set: multi-device subscribe /
        # unsubscribe is O(1) and idempotent).
        self._subscribers: dict[str, set[Subscription]] = {}

    def subscribe(self, user_id: str) -> Subscription:
        """Register a new firehose connection for ``user_id``."""
        sub = Subscription(user_id)
        self._subscribers.setdefault(user_id, set()).add(sub)
        logger.debug(
            "firehose.subscribe",
            user=user_id,
            conns=len(self._subscribers[user_id]),
        )
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """Remove a connection (on disconnect); drop the user entry when empty."""
        conns = self._subscribers.get(sub.user_id)
        if conns is None:
            return
        conns.discard(sub)
        if not conns:
            self._subscribers.pop(sub.user_id, None)
        logger.debug("firehose.unsubscribe", user=sub.user_id)

    def connection_count(self, user_id: str) -> int:
        """How many live firehose connections ``user_id`` currently holds."""
        return len(self._subscribers.get(user_id, ()))

    def is_online(self, user_id: str) -> bool:
        """True when ``user_id`` holds ≥1 live ``/v1/realtime`` subscription."""
        return self.connection_count(user_id) > 0

    def online_user_ids(self) -> frozenset[str]:
        """User ids with ≥1 live firehose connection (admin + IM presence read model)."""
        return frozenset(self._subscribers)

    def online_user_count(self) -> int:
        """Distinct users currently online (same semantics as :meth:`online_user_ids`)."""
        return len(self._subscribers)

    async def publish(self, user_ids: Sequence[str], event: dict[str, Any]) -> None:
        """Fan ``event`` out to every live connection of each user (best-effort).

        Synchronous in effect (no ``await`` points) so the subscriber map cannot
        change mid-fan-out; duplicate ``user_ids`` deliver once per connection.
        Declared ``async`` to satisfy the ``ChatEventPublisher`` seam.
        """
        for user_id in set(user_ids):
            for sub in tuple(self._subscribers.get(user_id, ())):
                if not sub._offer(event):
                    logger.warning(
                        "firehose.backpressure_drop",
                        user=user_id,
                        type=event.get("type"),
                    )


class HubChatEventPublisher:
    """``ChatEventPublisher`` backed by the in-process :class:`ChatHub`.

    Wired into ``MessagingService`` (via the DI provider) so a persisted message
    fans out to recipients' firehoses. Swappable for a Redis / NATS publisher
    behind the same ``publish`` seam when scaling past one worker.
    """

    def __init__(self, hub: ChatHub) -> None:
        self._hub = hub

    async def publish(self, user_ids: Sequence[str], event: dict[str, Any]) -> None:
        await self._hub.publish(user_ids, event)


_hub = ChatHub()


def default_chat_hub() -> ChatHub:
    """The process-wide chat hub (shared by the publisher + the firehose route)."""
    return _hub
