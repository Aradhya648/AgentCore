"""Native push notifications (原生推送, 认证与会话 §十).

A best-effort backstop for the *attention* signal when the mobile client is gone
(SSE dropped, app backgrounded): when an agent durably pauses for the user
(plan_review / ask_user), :func:`notify_user` fans a notification out to that user's
registered device tokens via the configured :class:`PushSender`.

Default-OFF: with ``settings.push_enabled`` false (the default), :func:`build_push_sender`
returns :class:`NullPushSender` and :func:`notify_user` short-circuits before any DB hit,
so a turn carries ZERO push overhead until an operator configures FCM.
"""

from agentcore.push.notify import notify_user
from agentcore.push.sender import (
    NullPushSender,
    PushNotification,
    PushSender,
    build_push_sender,
)

__all__ = [
    "NullPushSender",
    "PushNotification",
    "PushSender",
    "build_push_sender",
    "notify_user",
]
