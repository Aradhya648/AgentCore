"""每用户实时 firehose (消息IM.md §四): one long-lived SSE stream per user.

The 消息 page's "对方" is another person's client, so the server must fan A's
message out to B — this channel is that delivery path (server→client only;
sending stays POST). Carries ``chat_message``, ``presence`` (online transitions
to co-chat users), ``friend_request`` (created/accepted/rejected/cancelled),
``memory_updated``, and shared-space nudges. Typing remains
⏳ (消息IM.md §七).

Auth is the access-token cookie, like every route. SSE cannot refresh a token
mid-stream, so on a 401 the client reconnects after a refresh (认证与会话 §六) —
opening the firehose just needs a valid cookie. Anything missed while
disconnected is re-synced on reconnect via the chat's ``last_read_message_id``
(离线补偿), so the stream is best-effort, not durable.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Coroutine

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from agentcore.api.dependencies import AuthUser
from agentcore.core.logging import get_logger
from agentcore.messaging.hub import ChatHub, Subscription, default_chat_hub
from agentcore.messaging.presence import broadcast_presence

logger = get_logger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])

# Idle gap after which a heartbeat comment is sent, to keep the connection (and
# any proxy in front of it) warm and to surface a dead peer as a write failure.
_HEARTBEAT_SECONDS = 25.0

type PresenceNotifier = Callable[[str, bool], Coroutine[None, None, None]]


def _format_event(event: dict) -> str:
    """Serialize a hub event dict as one ``text/event-stream`` frame."""
    event_type = str(event.get("type", "message"))
    data = json.dumps(event, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"


def _schedule_presence(user_id: str, *, online: bool) -> None:
    """Fire-and-forget presence fan-out (must not delay / break the SSE loop)."""

    async def _run() -> None:
        try:
            await broadcast_presence(user_id, online=online)
        except Exception:  # noqa: BLE001
            logger.warning("presence.broadcast_failed", user=user_id, online=online, exc_info=True)

    asyncio.create_task(_run())


async def _firehose(
    sub: Subscription,
    hub: ChatHub,
    *,
    notify_presence: PresenceNotifier | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames for ``sub`` until the client disconnects.

    A persistent ``get`` task is reused across heartbeat windows (never cancelled
    on a mere timeout) so a heartbeat can never race an event off the queue; it is
    only cancelled on teardown, when the connection is closing anyway.

    On the last connection drop for this user, ``notify_presence(user_id, False)``
    runs (when provided) so co-chat peers learn the offline transition.
    """
    # Open with a ``ready`` frame so the client confirms the stream is live before
    # any message arrives (and headers flush through a buffering proxy).
    # ``ready`` must be inside the ``try`` so client disconnect / ``aclose`` still
    # runs unsubscribe + offline presence (GeneratorExit at a pre-try yield skips
    # ``finally``).
    get_task: asyncio.Task[dict | None] | None = None
    try:
        yield _format_event({"type": "ready"})
        while True:
            if get_task is None:
                get_task = asyncio.ensure_future(sub.get())
            done, _ = await asyncio.wait({get_task}, timeout=_HEARTBEAT_SECONDS)
            if not done:
                yield ": keep-alive\n\n"  # SSE comment, ignored by EventSource
                continue
            event = get_task.result()
            get_task = None
            if event is None:  # hub closed this subscription
                return
            yield _format_event(event)
    finally:
        if get_task is not None:
            get_task.cancel()
        hub.unsubscribe(sub)
        # Offline only when this was the last live subscription (multi-device safe).
        if notify_presence is not None and not hub.is_online(sub.user_id):
            await notify_presence(sub.user_id, False)


@router.get("")
async def realtime_firehose(user: AuthUser) -> StreamingResponse:
    """Open this user's realtime firehose (server→client SSE).

    Subscribes the connection to the in-process hub; a new message in any chat the
    user belongs to arrives as a ``chat_message`` event. The first subscription
    (and last disconnect) also fans a ``presence`` event to co-chat users.
    Heartbeat comments keep the stream warm; the subscription is released when
    the client disconnects.
    """
    hub = default_chat_hub()
    became_online = not hub.is_online(user.user_id)
    sub = hub.subscribe(user.user_id)
    if became_online:
        _schedule_presence(user.user_id, online=True)

    async def _notify(user_id: str, online: bool) -> None:
        _schedule_presence(user_id, online=online)

    return StreamingResponse(
        _firehose(sub, hub, notify_presence=_notify),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
