"""IM presence fan-out: connect/disconnect → ``presence`` firehose events.

Online = ≥1 live ``/v1/realtime`` subscription on :class:`ChatHub` (same semantics
as the admin roster). Events are pushed only to users who share at least one chat
with the subject — never a site-wide broadcast. Not persisted (消息IM.md P1).
"""

from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import ChatRepository
from agentcore.messaging.hub import ChatHub, default_chat_hub

logger = get_logger(__name__)


def presence_event(*, user_id: str, online: bool) -> dict:
    """Canonical firehose payload for a presence transition."""
    return {"type": "presence", "user_id": user_id, "online": online}


async def list_presence_audience(user_id: str) -> list[str]:
    """User ids that share ≥1 chat with ``user_id`` (excludes the subject)."""
    async with async_session_factory() as session:
        return await ChatRepository(session).list_co_member_ids(user_id)


async def broadcast_presence(
    user_id: str,
    *,
    online: bool,
    hub: ChatHub | None = None,
) -> None:
    """Notify co-chat users that ``user_id`` went online or offline (best-effort)."""
    try:
        audience = await list_presence_audience(user_id)
    except Exception:  # noqa: BLE001 — presence must never break the firehose
        logger.warning("presence.audience_failed", user=user_id, exc_info=True)
        return
    if not audience:
        return
    target = hub or default_chat_hub()
    event = presence_event(user_id=user_id, online=online)
    await target.publish(audience, event)
    logger.debug(
        "presence.broadcast",
        user=user_id,
        online=online,
        audience=len(audience),
    )
