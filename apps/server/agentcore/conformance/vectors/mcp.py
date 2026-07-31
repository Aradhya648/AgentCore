"""Local MCP Client (mcp_op_required) conformance scenarios."""

from __future__ import annotations

from collections.abc import Callable

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    approval_required,
    approval_resolved,
    content_delta,
    mcp_op_required,
    message_end,
    message_start,
    reasoning_delta,
    tool_use_end,
    tool_use_start,
)

from ._common import _CONV, _COST

_REQ_ID = "mcp-req-1"
_TOOL_NAME = "mcp_echo_ping"
_TOOL_ARGS = {"message": "hi"}
_CALL_ARGS = {
    "server_id": "echo",
    "tool_name": "ping",
    "arguments": _TOOL_ARGS,
}


def _mcp_call_tool_applied() -> list[SSEEvent]:
    """MCP：worker 调动态工具 → mcp_op_required 运输 → 工具成功 → 回合收尾。

    ``mcp_op_required`` is transport-only (desktop stdio Client + settle); it does not
    pause the turn or alter ``ProjectedTurn`` — same no-op fold as ``host_op_required`` /
    ``board_op_required``. The ``mcp_*`` tool step still lands on the process timeline.
    """
    return [
        message_start("m1", conversation_id=_CONV),
        reasoning_delta("先通过本机 MCP 探测 echo server。"),
        tool_use_start("tc1", _TOOL_NAME, _TOOL_ARGS),
        mcp_op_required(
            request_id=_REQ_ID,
            conversation_id=_CONV,
            op="call_tool",
            args=_CALL_ARGS,
        ),
        tool_use_end(
            "tc1",
            _TOOL_NAME,
            success=True,
            output='{"content":[{"type":"text","text":"pong"}]}',
        ),
        content_delta("MCP echo 返回 pong。"),
        message_end(FinishReason.END_TURN, input_tokens=1100, output_tokens=120, cost=_COST),
    ]


def _mcp_call_tool_failed() -> list[SSEEvent]:
    """MCP：桌面回填失败 — 工具步仍落在时间线，回合照常收尾。"""
    return [
        message_start("m1", conversation_id=_CONV),
        tool_use_start("tc1", _TOOL_NAME, _TOOL_ARGS),
        mcp_op_required(
            request_id=_REQ_ID,
            conversation_id=_CONV,
            op="call_tool",
            args=_CALL_ARGS,
        ),
        tool_use_end(
            "tc1",
            _TOOL_NAME,
            success=False,
            output="MCP Server 握手失败\n--- MCP stderr ---\nspawn ENOENT",
        ),
        content_delta("本机 MCP 不可用，已如实说明。"),
        message_end(FinishReason.END_TURN, input_tokens=800, output_tokens=60, cost=_COST),
    ]


def _mcp_call_with_approval() -> list[SSEEvent]:
    """MCP GRANTABLE：通用 Approval 卡通过后再走 mcp_op_required 运输（生产顺序）。

    Production ``tool_exec`` emits ``tool_use_start`` before the approval suspend;
    desktop fulfills via the same ApprovalPrompt surface (no MCP-specific card).
    """
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("需要调用本机 MCP 工具。"),
        tool_use_start("tc1", _TOOL_NAME, _TOOL_ARGS),
        approval_required(
            approval_id="tc1",
            conversation_id=_CONV,
            tool_call_id="tc1",
            tool_name=_TOOL_NAME,
            arguments=_TOOL_ARGS,
        ),
        approval_resolved(approval_id="tc1", tool_call_id="tc1", decision="approve"),
        mcp_op_required(
            request_id=_REQ_ID,
            conversation_id=_CONV,
            op="call_tool",
            args=_CALL_ARGS,
        ),
        tool_use_end(
            "tc1",
            _TOOL_NAME,
            success=True,
            output='{"content":[{"type":"text","text":"pong"}]}',
        ),
        content_delta("已获授权并完成 MCP 调用。"),
        message_end(FinishReason.END_TURN, input_tokens=1000, output_tokens=90, cost=_COST),
    ]


VECTORS: dict[str, tuple[str, Callable[[], list[SSEEvent]]]] = {
    "mcp_call_tool_applied": (
        "MCP：call_tool 成功（mcp_op_required 运输 + 工具步 + end_turn）",
        _mcp_call_tool_applied,
    ),
    "mcp_call_tool_failed": (
        "MCP：call_tool 握手/回填失败（工具步失败 + 回合仍收尾）",
        _mcp_call_tool_failed,
    ),
    "mcp_call_with_approval": (
        "MCP：GRANTABLE 通用审批通过后 mcp_op_required + 成功收尾",
        _mcp_call_with_approval,
    ),
}
