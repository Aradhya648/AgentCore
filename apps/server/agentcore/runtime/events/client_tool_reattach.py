"""Re-emit open CLIENT_TOOL ``*_required`` frames on SSE attach.

``*_op_required`` / notify / board_read stay EPHEMERAL (not journaled). On refresh,
attach replays DURABLE journal (or sink history), then re-sends still-open client_tool
requests from the in-process registry so the desktop can fulfil them. Done /
cancelled / discarded entries are absent from ``list_pending`` and are not re-sent.
Process restart / no live turn (204) does not promise reattach.
"""

from __future__ import annotations

from typing import Any

from agentcore.runtime.events.board import board_op_required, board_read_required
from agentcore.runtime.events.desktop import (
    desktop_notify_required,
    host_op_required,
    mcp_op_required,
)
from agentcore.runtime.events.types import SSEEvent
from agentcore.runtime.events.workspace import workspace_op_required
from agentcore.runtime.interaction import InteractionKind, InteractionRequest

# Stable channel tags written into ``InteractionRequest.payload`` at suspend.
CHANNEL_HOST = "host"
CHANNEL_MCP = "mcp"
CHANNEL_WORKSPACE = "workspace"
CHANNEL_BOARD = "board"
CHANNEL_BOARD_READ = "board_read"
CHANNEL_NOTIFY = "notify"

# Meta keys on the registry payload (not forwarded into the SSE wire body).
_META_KEYS = frozenset({"channel", "event_type"})


def client_tool_payload(
    channel: str,
    event_type: str,
    *,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Registry payload: stable channel/event_type + original op params."""
    return {"channel": channel, "event_type": event_type, **params}


def build_client_tool_required(req: InteractionRequest) -> SSEEvent | None:
    """Rebuild the EPHEMERAL ``*_required`` SSE for one open CLIENT_TOOL request."""
    if req.kind != InteractionKind.CLIENT_TOOL:
        return None
    if req.future.done():
        return None
    channel = req.payload.get("channel")
    if not isinstance(channel, str) or not channel:
        # Prefer explicit event_type when channel is missing (older in-flight entries).
        channel = _channel_from_event_type(req.payload.get("event_type"))
    if channel is None:
        return None

    params = {k: v for k, v in req.payload.items() if k not in _META_KEYS}
    rid = req.id
    cid = req.conversation_id

    if channel == CHANNEL_WORKSPACE:
        raw_timeout = params.get("timeout_ms")
        timeout_ms: int | None = None
        if isinstance(raw_timeout, int) and raw_timeout > 0:
            timeout_ms = raw_timeout
        elif isinstance(raw_timeout, float) and raw_timeout > 0:
            timeout_ms = int(raw_timeout)
        return workspace_op_required(
            request_id=rid,
            conversation_id=cid,
            root_id=str(params.get("root_id") or ""),
            op=str(params.get("op") or ""),
            args=dict(params.get("args") or {}),
            timeout_ms=timeout_ms,
        )
    if channel == CHANNEL_BOARD:
        ops = params.get("ops")
        return board_op_required(
            request_id=rid,
            conversation_id=cid,
            board_id=str(params.get("board_id") or ""),
            ops=list(ops) if isinstance(ops, list) else [],
            summary=str(params.get("summary") or ""),
        )
    if channel == CHANNEL_BOARD_READ:
        ids = params.get("ids")
        return board_read_required(
            request_id=rid,
            conversation_id=cid,
            board_id=str(params.get("board_id") or ""),
            ids=list(ids) if isinstance(ids, list) else [],
        )
    if channel == CHANNEL_HOST:
        return host_op_required(
            request_id=rid,
            conversation_id=cid,
            op=str(params.get("op") or ""),
            args=dict(params.get("args") or {}),
        )
    if channel == CHANNEL_MCP:
        return mcp_op_required(
            request_id=rid,
            conversation_id=cid,
            op=str(params.get("op") or ""),
            args=dict(params.get("args") or {}),
        )
    if channel == CHANNEL_NOTIFY:
        return desktop_notify_required(
            request_id=rid,
            conversation_id=cid,
            title=str(params.get("title") or ""),
            body=str(params.get("body") or ""),
        )
    return None


def pending_client_tool_events(conversation_id: str) -> list[SSEEvent]:
    """Open CLIENT_TOOL ``*_required`` frames for one conversation (attach re-hang)."""
    from agentcore.runtime.interaction import default_interaction_registry

    out: list[SSEEvent] = []
    for req in default_interaction_registry().list_pending(conversation_id):
        event = build_client_tool_required(req)
        if event is not None:
            out.append(event)
    return out


def _channel_from_event_type(event_type: Any) -> str | None:
    if not isinstance(event_type, str):
        return None
    return {
        "workspace_op_required": CHANNEL_WORKSPACE,
        "board_op_required": CHANNEL_BOARD,
        "board_read_required": CHANNEL_BOARD_READ,
        "host_op_required": CHANNEL_HOST,
        "mcp_op_required": CHANNEL_MCP,
        "desktop_notify_required": CHANNEL_NOTIFY,
    }.get(event_type)
