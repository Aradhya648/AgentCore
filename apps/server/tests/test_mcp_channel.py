"""Unit tests for local MCP Client channel + dynamic worker tools."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from agentcore.core.types import ToolApproval
from agentcore.desktop.channel import DesktopClientChannel, McpOp, McpOpError
from agentcore.runtime.events.client_tool_reattach import (
    CHANNEL_MCP,
    build_client_tool_required,
    client_tool_payload,
)
from agentcore.runtime.events.types import EventType
from agentcore.runtime.interaction import InteractionKind, InteractionRequest
from agentcore.tools.builtin import build_ceo_tool_registry, build_worker_registry
from agentcore.tools.mcp.dynamic import McpDynamicTool, sanitize_mcp_tool_name
from agentcore.tools.mcp.wire import (
    McpDiscoverResult,
    McpToolSpec,
    discover_mcp_tools,
    mcp_capability_label,
    register_mcp_tools,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry


def test_sanitize_mcp_tool_name_stable_and_bounded():
    name = sanitize_mcp_tool_name("my-server!", "list/files")
    assert name.startswith("mcp_")
    assert len(name) <= 64
    assert "/" not in name
    assert "!" not in name


def test_mcp_capability_label_matrix():
    assert mcp_capability_label(None, desktop_online=False) == "未装配"
    assert mcp_capability_label(None, desktop_online=True) == "未装配"
    ready = McpDiscoverResult(tool_count=2, ready_servers=1)
    assert mcp_capability_label(ready, desktop_online=True) == "已装配"
    degraded = McpDiscoverResult(degraded=True, failed_servers=1)
    assert mcp_capability_label(degraded, desktop_online=True) == "降级（无可用工具）"


def test_register_mcp_tools_worker_only_grantable():
    registry = ToolRegistry()
    result = McpDiscoverResult(
        ready_servers=1,
        tool_count=1,
        specs=(
            McpToolSpec(
                server_id="echo",
                server_name="Echo",
                mcp_tool_name="ping",
                description="Ping",
                input_schema={"type": "object", "properties": {}},
            ),
        ),
    )
    assert register_mcp_tools(registry, result) == 1
    tool = registry.get("mcp_echo_ping")
    assert tool.schema.approval is ToolApproval.GRANTABLE
    assert "MCP" in tool.schema.description


def test_desktop_touch_tool_names_cover_mcp_and_host():
    from agentcore.runtime.sandbox_approval import is_desktop_touch_tool

    assert is_desktop_touch_tool("mcp_echo_ping")
    assert is_desktop_touch_tool("host_shell")
    assert not is_desktop_touch_tool("file_write")
    assert not is_desktop_touch_tool("web_search")


def test_resolve_worker_gate_shares_gate_for_mcp_on_cloud():
    from types import SimpleNamespace

    from agentcore.runtime.delegate.drive_setup import resolve_worker_gate
    from agentcore.tools.mcp.dynamic import McpDynamicTool

    registry = ToolRegistry()
    registry.register(
        McpDynamicTool(
            fc_name="mcp_echo_ping",
            server_id="echo",
            server_name="Echo",
            mcp_tool_name="ping",
            description="Ping",
            input_schema=None,
        )
    )
    gate = object()
    backend = SimpleNamespace(location="server")
    tool = SimpleNamespace(
        _approval_gate=gate,
        _tools=registry,
        _base_tool_context=SimpleNamespace(backend=backend),
    )
    assert resolve_worker_gate(tool) is gate

    empty = ToolRegistry()
    tool_no_mcp = SimpleNamespace(
        _approval_gate=gate,
        _tools=empty,
        _base_tool_context=SimpleNamespace(backend=backend),
    )
    assert resolve_worker_gate(tool_no_mcp) is None


def test_ceo_registry_has_no_mcp_tools_by_default():
    ceo = {s.name for s in build_ceo_tool_registry(desktop_online=True).list_all()}
    worker = build_worker_registry(desktop_online=True)
    register_mcp_tools(
        worker,
        McpDiscoverResult(
            tool_count=1,
            specs=(
                McpToolSpec(
                    server_id="s",
                    server_name="S",
                    mcp_tool_name="t",
                    description="d",
                    input_schema=None,
                ),
            ),
        ),
    )
    worker_names = {s.name for s in worker.list_all()}
    assert "mcp_s_t" in worker_names
    assert not any(n.startswith("mcp_") for n in ceo)


@pytest.mark.asyncio
async def test_discover_mcp_tools_degrades_without_channel():
    result = await discover_mcp_tools(None)
    assert result.tool_count == 0
    assert result.detail == "no_desktop_channel"


@pytest.mark.asyncio
async def test_discover_mcp_tools_parses_ready_and_failed():
    channel = DesktopClientChannel(
        sink=AsyncMock(),
        conversation_id="c1",
        registry=AsyncMock(),
        timeout_seconds=5,
    )
    channel.request_mcp = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "servers": [
                {
                    "id": "ok",
                    "name": "OK",
                    "status": "ready",
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                            },
                        }
                    ],
                },
                {
                    "id": "bad",
                    "name": "Bad",
                    "status": "failed",
                    "error": "spawn failed",
                    "tools": [],
                },
            ]
        }
    )
    result = await discover_mcp_tools(channel)
    assert result.ready_servers == 1
    assert result.failed_servers == 1
    assert result.tool_count == 1
    assert result.specs[0].mcp_tool_name == "echo"


@pytest.mark.asyncio
async def test_discover_mcp_tools_degrades_on_timeout():
    channel = DesktopClientChannel(
        sink=AsyncMock(),
        conversation_id="c1",
        registry=AsyncMock(),
        timeout_seconds=5,
    )
    channel.request_mcp = AsyncMock(  # type: ignore[method-assign]
        side_effect=McpOpError("timeout")
    )
    result = await discover_mcp_tools(channel)
    assert result.degraded
    assert result.tool_count == 0


@pytest.mark.asyncio
async def test_request_mcp_emits_mcp_op_required():
    emitted: list[Any] = []

    class _Sink:
        def emit(self, event: Any) -> None:
            emitted.append(event)

    async def _suspend(*_a, **kwargs):
        on_suspended = kwargs.get("on_suspended")
        if callable(on_suspended):
            on_suspended()
        return {"ok": True, "value": {"servers": []}}

    registry = AsyncMock()
    registry.suspend = AsyncMock(side_effect=_suspend)
    channel = DesktopClientChannel(
        sink=_Sink(),  # type: ignore[arg-type]
        conversation_id="c1",
        registry=registry,
        timeout_seconds=5,
    )
    value = await channel.request_mcp(McpOp.LIST_TOOLS, {})
    assert value == {"servers": []}
    assert len(emitted) == 1
    assert emitted[0].type.value == "mcp_op_required"
    assert emitted[0].payload["op"] == "list_tools"


@pytest.mark.asyncio
async def test_mcp_dynamic_tool_call_and_no_channel():
    from unittest.mock import MagicMock

    tool = McpDynamicTool(
        fc_name="mcp_s_echo",
        server_id="s",
        server_name="S",
        mcp_tool_name="echo",
        description="Echo",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="r",
        agent_id="a",
        backend=MagicMock(location="server"),
        user_id="u1",
        desktop_channel=None,
    )
    miss = await tool.execute({"text": "hi"}, ctx)
    assert not miss.success
    assert "桌面" in (miss.error or "")

    channel = AsyncMock()
    channel.request_mcp = AsyncMock(return_value={"content": "hi", "isError": False})
    ctx2 = ToolContext(
        execution_id="e",
        run_id="r",
        agent_id="a",
        backend=MagicMock(location="server"),
        user_id="u1",
        desktop_channel=channel,
    )
    ok = await tool.execute({"text": "hi"}, ctx2)
    assert ok.success
    assert ok.output == "hi"
    channel.request_mcp.assert_awaited_once()


def test_mcp_reattach_rebuilds_required_event():
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        req = InteractionRequest(
            id="rid",
            kind=InteractionKind.CLIENT_TOOL,
            conversation_id="c1",
            future=loop.create_future(),
            payload=client_tool_payload(
                CHANNEL_MCP,
                EventType.MCP_OP_REQUIRED.value,
                params={"op": "call_tool", "args": {"server_id": "s", "tool_name": "t"}},
            ),
        )
        event = build_client_tool_required(req)
        assert event is not None
        assert event.type.value == "mcp_op_required"
        assert event.payload["op"] == "call_tool"
    finally:
        loop.close()
