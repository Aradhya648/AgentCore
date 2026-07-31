"""Capacity contract vs liveness timeout for FILESYSTEM tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentcore.runtime.loop_controller import CircuitBreak, LoopController, ToolAttempt
from agentcore.runtime.tool_deadline import (
    current_tool_deadline,
    derive_channel_timeout,
    reset_tool_deadline,
    set_tool_deadline,
)
from agentcore.tools.builtin.file_ops import FileReadTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.limits import (
    FILE_TOO_LARGE_DETAIL,
    OFFICE_EXTRACT_MAX_BYTES,
    WORKSPACE_READ_MAX_BYTES,
)
from agentcore.workspace.protocol import WorkspaceIOError
from agentcore.workspace.server import ServerWorkspace


def _ws(root: Path) -> ServerWorkspace:
    return ServerWorkspace(root=root, sandbox=SubprocessSandbox())


def _ctx(ws: ServerWorkspace) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a1",
        backend=ws,
        user_id="u",
    )


@pytest.mark.asyncio
async def test_server_workspace_read_rejects_over_5mib(tmp_path: Path):
    big = tmp_path / "huge.bin"
    big.write_bytes(b"x" * (WORKSPACE_READ_MAX_BYTES + 1))
    ws = _ws(tmp_path)
    with pytest.raises(WorkspaceIOError) as ei:
        await ws.read("huge.bin")
    assert str(ei.value) == FILE_TOO_LARGE_DETAIL


@pytest.mark.asyncio
async def test_server_workspace_read_bytes_rejects_over_5mib(tmp_path: Path):
    big = tmp_path / "huge.bin"
    big.write_bytes(b"x" * (WORKSPACE_READ_MAX_BYTES + 1))
    ws = _ws(tmp_path)
    with pytest.raises(WorkspaceIOError) as ei:
        await ws.read_bytes("huge.bin")
    assert str(ei.value) == FILE_TOO_LARGE_DETAIL


@pytest.mark.asyncio
async def test_file_read_oversized_is_contract_failure(tmp_path: Path):
    big = tmp_path / "huge.txt"
    big.write_bytes(b"a" * (WORKSPACE_READ_MAX_BYTES + 1))
    result = await FileReadTool().execute({"path": "huge.txt"}, _ctx(_ws(tmp_path)))
    assert result.success is False
    assert result.contract_failure is True
    assert "MiB" in (result.error or "")
    assert result.metadata.get("capacity_contract") == "bytes"


@pytest.mark.asyncio
async def test_file_read_office_extract_budget_is_contract(tmp_path: Path):
    # Under whole-file read max but over extract budget.
    path = tmp_path / "deck.pdf"
    path.write_bytes(b"%PDF-" + b"x" * (OFFICE_EXTRACT_MAX_BYTES + 100))
    assert WORKSPACE_READ_MAX_BYTES > len(path.read_bytes()) > OFFICE_EXTRACT_MAX_BYTES
    result = await FileReadTool().execute({"path": "deck.pdf"}, _ctx(_ws(tmp_path)))
    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata.get("capacity_contract") == "extract_bytes"
    assert "抽取预算" in (result.error or "")


@pytest.mark.asyncio
async def test_file_read_channel_liveness_maps_meta(tmp_path: Path):
    class _HangBackend(ServerWorkspace):
        async def read(self, path: str) -> str:  # noqa: ARG002
            raise WorkspaceIOError("local workspace op 'read' timed out（活性挂起）")

    result = await FileReadTool().execute(
        {"path": "a.txt"}, _ctx(_HangBackend(tmp_path, sandbox=SubprocessSandbox()))
    )
    assert result.success is False
    assert result.contract_failure is False
    assert result.metadata.get("liveness_timeout") is True
    assert "活性挂起" in (result.error or "")
    assert "禁止原样重试" in (result.error or "")


def test_derive_channel_timeout_from_outer_deadline():
    token = set_tool_deadline(60.0)
    try:
        assert current_tool_deadline() == 60.0
        # Slave ≤ outer − slack
        assert derive_channel_timeout(channel_default=60.0) == 59.0
        assert derive_channel_timeout(explicit=90.0, channel_default=60.0) == 59.0
        assert derive_channel_timeout(explicit=30.0, channel_default=60.0) == 30.0
    finally:
        reset_tool_deadline(token)
    assert current_tool_deadline() is None
    assert derive_channel_timeout(channel_default=60.0) == 60.0


def test_liveness_circuit_warn_steer():
    ctrl = LoopController(
        tool_failure_warn=2,
        tool_failure_disable=3,
        unproductive_threshold=99,
        reflection_start_round=99,
        reflection_interval=99,
    )
    for _ in range(2):
        ctrl.record(
            [
                ToolAttempt(
                    "fp",
                    "file_read",
                    success=False,
                    error_summary="活性挂起",
                    meta={"liveness_timeout": True},
                )
            ]
        )
    br = ctrl.tool_circuit_breaker()
    assert br.warned == ("file_read",)
    assert "file_read" in br.liveness_warned
    msg = br.message() or ""
    assert "活性挂起" in msg
    assert "原样重试" in msg


def test_circuit_break_liveness_field_defaults():
    assert CircuitBreak().liveness_warned == frozenset()
