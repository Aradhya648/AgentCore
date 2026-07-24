"""Tests for the worker-only ``terminal`` background-process tool (M1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentcore.config import settings
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.runtime.approvals import tool_call_requires_approval
from agentcore.runtime.engine import resolve_tool_timeout
from agentcore.runtime.events import EventSink, EventType, SSEEvent
from agentcore.runtime.interaction import InteractionRegistry
from agentcore.tools.builtin import (
    build_builtin_registry,
    build_ceo_tool_registry,
    build_worker_registry,
    delegation_grantable_tool_names,
)
from agentcore.tools.builtin.terminal import (
    TerminalTool,
    clamp_wait_timeout_seconds,
    terminal_approval_subcommands,
    terminal_op_timeout_seconds,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.channel import WorkspaceChannel, WorkspaceOp
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.server import ServerWorkspace

pytestmark = pytest.mark.anyio

CONV = "conv-terminal-1"
ROOT_ID = "root-terminal"


def _drain(sink: EventSink) -> list[SSEEvent]:
    events: list[SSEEvent] = []
    while not sink._queue.empty():  # noqa: SLF001
        events.append(sink._queue.get_nowait())
    return events


async def _await_request(sink: EventSink) -> SSEEvent:
    for _ in range(2000):
        if not sink._queue.empty():  # noqa: SLF001
            return sink._queue.get_nowait()
        await asyncio.sleep(0)
    raise AssertionError("no workspace_op_required event emitted")


async def _round_trip(
    coro: Any, sink: EventSink, registry: InteractionRegistry, response: dict[str, Any]
):
    task = asyncio.create_task(coro)
    event = await _await_request(sink)
    assert registry.resolve(event.payload["request_id"], response, conversation_id=CONV)
    return await task, event


def _ctx(channel: WorkspaceChannel | None) -> ToolContext:
    return ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="w1",
        backend=MagicMock(location="local"),
        user_id="u1",
        conversation_id=CONV,
        workspace_channel=channel,
    )


def _channel(timeout: float = 5.0) -> tuple[WorkspaceChannel, InteractionRegistry, EventSink]:
    sink = EventSink()
    registry = InteractionRegistry()
    channel = WorkspaceChannel(
        sink=sink,
        conversation_id=CONV,
        registry=registry,
        timeout_seconds=timeout,
        root_id=ROOT_ID,
    )
    return channel, registry, sink


# --- schema / approval / registry ------------------------------------------


def test_terminal_schema_is_never_execution():
    schema = TerminalTool().schema
    assert schema.name == "terminal"
    assert schema.approval is ToolApproval.NEVER
    assert schema.category is ToolCategory.EXECUTION
    assert "start" in schema.parameters["properties"]["subcommand"]["enum"]
    assert terminal_approval_subcommands() == frozenset({"start"})


def test_tool_call_requires_approval_only_for_start():
    schema = TerminalTool().schema
    assert (
        tool_call_requires_approval("terminal", schema.approval, {"subcommand": "start"}) is True
    )
    for sub in ("read", "stop", "list"):
        assert (
            tool_call_requires_approval("terminal", schema.approval, {"subcommand": sub}) is False
        )


def test_terminal_not_in_builtin_or_ceo_registry():
    assert "terminal" not in {s.name for s in build_builtin_registry().list_all()}
    assert "terminal" not in {s.name for s in build_ceo_tool_registry().list_all()}


def test_worker_registry_registers_terminal_only_on_local():
    local = ServerWorkspace(
        root=Path("."), sandbox=SubprocessSandbox(), location="local"
    )
    server = ServerWorkspace(
        root=Path("."), sandbox=SubprocessSandbox(), location="server"
    )
    assert "terminal" in {s.name for s in build_worker_registry(backend=local).list_all()}
    assert "terminal" not in {s.name for s in build_worker_registry(backend=server).list_all()}
    assert "terminal" not in {s.name for s in build_worker_registry().list_all()}


def test_delegation_grantable_includes_terminal():
    assert "terminal" in delegation_grantable_tool_names()


def test_resolve_tool_timeout_raises_for_wait_for():
    schema = TerminalTool().schema
    slack = settings.workspace_execute_timeout_slack_seconds
    assert resolve_tool_timeout(schema, {"subcommand": "start", "command": "x"}) == 60.0
    wait_args = {
        "subcommand": "start",
        "command": "x",
        "wait_for": "ready",
        "wait_timeout_seconds": 45,
    }
    assert resolve_tool_timeout(schema, wait_args) == 45.0 + slack
    assert terminal_op_timeout_seconds(wait_args) == resolve_tool_timeout(schema, wait_args)


def test_clamp_wait_timeout_bounds():
    assert clamp_wait_timeout_seconds(None) == 30.0
    assert clamp_wait_timeout_seconds(0) == 1.0
    assert clamp_wait_timeout_seconds(9999) == 300.0


# --- op contract serialization ---------------------------------------------


async def test_start_emits_process_start_op_and_formats_result():
    channel, registry, sink = _channel()
    tool = TerminalTool()
    response = {
        "ok": True,
        "value": {
            "process_id": "p1",
            "status": "running",
            "output": "Listening on :3000\n",
            "matched": True,
        },
    }
    result, event = await _round_trip(
        tool.execute(
            {
                "subcommand": "start",
                "command": "pnpm dev",
                "cwd": "apps/web",
                "wait_for": "Listening",
                "wait_timeout_seconds": 20,
                "name": "web",
            },
            _ctx(channel),
        ),
        sink,
        registry,
        response,
    )
    assert event.type is EventType.WORKSPACE_OP_REQUIRED
    assert event.payload["op"] == WorkspaceOp.PROCESS_START
    assert event.payload["args"] == {
        "command": "pnpm dev",
        "cwd": "apps/web",
        "wait_for": "Listening",
        "wait_timeout_seconds": 20.0,
        "name": "web",
    }
    assert result.success
    assert "process_id: p1" in result.output
    assert result.display == {
        "subcommand": "start",
        "process_id": "p1",
        "status": "running",
        "output": "Listening on :3000\n",
        "matched": True,
    }


async def test_read_stop_list_op_shapes():
    channel, registry, sink = _channel()
    tool = TerminalTool()

    read_resp = {
        "ok": True,
        "value": {
            "process_id": "p1",
            "status": "running",
            "output": "err line\n",
            "matched": False,
        },
    }
    result, event = await _round_trip(
        tool.execute(
            {"subcommand": "read", "process_id": "p1", "tail_lines": 40},
            _ctx(channel),
        ),
        sink,
        registry,
        read_resp,
    )
    assert event.payload["op"] == WorkspaceOp.PROCESS_READ
    assert event.payload["args"] == {"process_id": "p1", "tail_lines": 40}
    assert result.success and result.display["subcommand"] == "read"
    _drain(sink)

    stop_resp = {
        "ok": True,
        "value": {"process_id": "p1", "status": "exited", "exit_code": 0},
    }
    result, event = await _round_trip(
        tool.execute({"subcommand": "stop", "process_id": "p1"}, _ctx(channel)),
        sink,
        registry,
        stop_resp,
    )
    assert event.payload["op"] == WorkspaceOp.PROCESS_STOP
    assert event.payload["args"] == {"process_id": "p1"}
    assert "exit_code: 0" in result.output
    _drain(sink)

    list_resp = {
        "ok": True,
        "value": {
            "processes": [
                {
                    "process_id": "p1",
                    "name": "web",
                    "command": "pnpm dev",
                    "status": "exited",
                    "started_at": "2026-07-12T00:00:00Z",
                    "exit_code": 0,
                }
            ]
        },
    }
    result, event = await _round_trip(
        tool.execute({"subcommand": "list"}, _ctx(channel)),
        sink,
        registry,
        list_resp,
    )
    assert event.payload["op"] == WorkspaceOp.PROCESS_LIST
    assert event.payload["args"] == {}
    assert "id=p1" in result.output
    assert result.display["subcommand"] == "list"


async def test_start_with_wait_for_extends_channel_timeout(monkeypatch):
    captured: list[float] = []
    real_wait_for = asyncio.wait_for

    async def spy(fut, timeout):  # noqa: ANN001
        captured.append(timeout)
        return await real_wait_for(fut, timeout)

    monkeypatch.setattr("agentcore.runtime.interaction.asyncio.wait_for", spy)

    channel, registry, sink = _channel(timeout=30.0)
    tool = TerminalTool()
    response = {
        "ok": True,
        "value": {"process_id": "p1", "status": "running", "output": "", "matched": True},
    }
    await _round_trip(
        tool.execute(
            {
                "subcommand": "start",
                "command": "pnpm dev",
                "wait_for": "ready",
                "wait_timeout_seconds": 40,
            },
            _ctx(channel),
        ),
        sink,
        registry,
        response,
    )
    slack = settings.workspace_execute_timeout_slack_seconds
    assert captured[-1] == 40.0 + slack


async def test_missing_channel_errors():
    result = await TerminalTool().execute({"subcommand": "list"}, _ctx(None))
    assert not result.success
    assert "本地" in (result.error or "")


async def test_local_workspace_reuses_channel_for_tools():
    """workspace_channel_for_tools must reuse LocalWorkspace._channel (same root_id)."""
    from agentcore.workspace.locate import workspace_channel_for_tools

    channel, _registry, sink = _channel()
    local = LocalWorkspace(channel)
    resolved = workspace_channel_for_tools(
        local, sink=sink, conversation_id=CONV
    )
    assert resolved is channel
