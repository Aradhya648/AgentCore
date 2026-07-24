"""Desktop Client Tools SSE event factories."""

from __future__ import annotations

from agentcore.runtime.events.types import EventType, SSEEvent


def desktop_notify_required(
    *,
    request_id: str,
    conversation_id: str,
    title: str,
    body: str = "",
) -> SSEEvent:
    """Ask the bound desktop to show an OS notification (transport-only client_tool)."""
    return SSEEvent(
        type=EventType.DESKTOP_NOTIFY_REQUIRED,
        payload={
            "request_id": request_id,
            "conversation_id": conversation_id,
            "title": title,
            "body": body,
        },
    )
