"""Desktop Client Tools SSE event factories."""

from __future__ import annotations

from typing import Any

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


def host_op_required(
    *,
    request_id: str,
    conversation_id: str,
    op: str,
    args: dict[str, Any] | None = None,
) -> SSEEvent:
    """Ask the bound desktop to run a Host op and report back (transport-only)."""
    return SSEEvent(
        type=EventType.HOST_OP_REQUIRED,
        payload={
            "request_id": request_id,
            "conversation_id": conversation_id,
            "op": op,
            "args": args or {},
        },
    )


def mcp_op_required(
    *,
    request_id: str,
    conversation_id: str,
    op: str,
    args: dict[str, Any] | None = None,
) -> SSEEvent:
    """Ask the bound desktop to run an MCP Client op (list/call) and report back."""
    return SSEEvent(
        type=EventType.MCP_OP_REQUIRED,
        payload={
            "request_id": request_id,
            "conversation_id": conversation_id,
            "op": op,
            "args": args or {},
        },
    )
