"""User-level push orchestration (原生推送下发, 认证与会话 §十).

:func:`notify_user` is the single best-effort entry the attention triggers call: it
resolves a user's device tokens, hands them to the configured :class:`PushSender`, and
prunes any the provider reports stale. It NEVER raises into the caller — a failed push
is a missed convenience, never a broken turn.

Uses ``async_session_factory`` directly (not a request session), matching the
suspension / cost-ledger persistence posture (the triggers run inside the turn pipeline,
outside any HTTP request).
"""

from __future__ import annotations

from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import PushDeviceRepository
from agentcore.push.sender import NullPushSender, PushNotification, build_push_sender

logger = get_logger(__name__)


async def notify_user(user_id: str, notification: PushNotification) -> None:
    """Push ``notification`` to all of ``user_id``'s registered devices (best-effort).

    Fast-paths to a no-op when push is disabled (the default) BEFORE touching the DB, so
    wiring this into a hot trigger costs nothing until FCM is configured. Stale tokens
    the provider rejects are pruned so a dead device stops being retried.
    """
    sender = build_push_sender()
    if isinstance(sender, NullPushSender):
        return
    try:
        async with async_session_factory() as db:
            repo = PushDeviceRepository(db)
            tokens = await repo.tokens_for_user(user_id)
            if not tokens:
                return
            dead = await sender.send(tokens, notification)
            if dead:
                await repo.delete_tokens(dead)
    except Exception as e:  # noqa: BLE001 — a push must never break the turn that triggered it
        logger.warning("push.notify_failed", user_id=user_id, error=str(e))
