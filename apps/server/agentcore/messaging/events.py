"""Realtime event publishing seam for the 消息 page (IM, 消息IM.md §四).

The service persists a chat message, then hands it to a publisher to fan out to
the recipients' live connections. The publisher is a seam so the service stays
unit-testable (a no-op fake) and the transport can change without touching
business logic: an in-process pub/sub hub now, Redis / NATS when multi-worker.
"""

from collections.abc import Sequence
from typing import Any, Protocol


class ChatEventPublisher(Protocol):
    """Fan a realtime event out to the given users' live connections."""

    async def publish(self, user_ids: Sequence[str], event: dict[str, Any]) -> None:
        """Best-effort deliver ``event`` to every connected session of each user."""
        ...


class NullChatEventPublisher:
    """No-op publisher — used in unit tests and when realtime is not wired."""

    async def publish(self, user_ids: Sequence[str], event: dict[str, Any]) -> None:
        return None
