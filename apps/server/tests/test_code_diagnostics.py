"""Tests for code_diagnostics tool + write-receipt attach helper."""

from __future__ import annotations

from typing import Any

import pytest

from agentcore.tools.builtin.code_diagnostics import CodeDiagnosticsTool
from agentcore.tools.builtin.write_diagnostics import (
    attach_write_diagnostics,
    is_js_ts_path,
)
from agentcore.tools.protocol import ToolContext, ToolResult


class _Backend:
    location = "server"
    root_label = "workspace"

    def __init__(self, payload: dict[str, Any] | None = None, *, raise_exc: Exception | None = None):
        self._payload = payload or {
            "status": "unavailable",
            "reason": "云端工作区暂不支持语言服务内环诊断",
            "diagnostics": [],
        }
        self._raise = raise_exc
        self.calls: list[list[str]] = []

    async def diagnostics(self, paths: list[str]) -> dict[str, Any]:
        self.calls.append(list(paths))
        if self._raise is not None:
            raise self._raise
        return self._payload


def _ctx(backend: _Backend, *, landed: dict[str, str] | None = None) -> ToolContext:
    return ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="a1",
        conversation_id="c1",
        user_id="u1",
        backend=backend,  # type: ignore[arg-type]
        landed_artifact_kinds=landed or {},
    )


def test_is_js_ts_path_suffixes():
    assert is_js_ts_path("src/a.ts")
    assert is_js_ts_path("src/a.tsx")
    assert is_js_ts_path("lib/x.mjs")
    assert not is_js_ts_path("readme.md")
    assert not is_js_ts_path("a.ts.bak")


@pytest.mark.asyncio
async def test_code_diagnostics_server_unavailable():
    backend = _Backend()
    result = await CodeDiagnosticsTool().execute(
        {"paths": ["src/a.ts"]},
        _ctx(backend),
    )
    assert result.success is True
    assert "内环诊断不可用" in result.output
    assert "test_run" in result.output
    assert result.display is not None
    assert result.display["kind"] == "code_diagnostics"
    assert result.display["status"] == "unavailable"
    assert backend.calls == [["src/a.ts"]]


@pytest.mark.asyncio
async def test_code_diagnostics_ok_lists_errors():
    backend = _Backend(
        {
            "status": "ok",
            "diagnostics": [
                {
                    "path": "src/a.ts",
                    "line": 3,
                    "column": 1,
                    "severity": "error",
                    "message": "Cannot find name 'x'",
                    "code": "2304",
                }
            ],
        }
    )
    result = await CodeDiagnosticsTool().execute(
        {"paths": ["src/a.ts"]},
        _ctx(backend),
    )
    assert result.success is True
    assert "Cannot find name 'x'" in result.output
    assert result.display["status"] == "ok"
    assert len(result.display["diagnostics"]) == 1


@pytest.mark.asyncio
async def test_code_diagnostics_defaults_to_landed_ts():
    backend = _Backend({"status": "ok", "diagnostics": []})
    result = await CodeDiagnosticsTool().execute(
        {},
        _ctx(backend, landed={"src/a.ts": "skeleton", "notes.md": "prose"}),
    )
    assert result.success is True
    assert backend.calls == [["src/a.ts"]]


@pytest.mark.asyncio
async def test_attach_write_diagnostics_ok_appends_block():
    backend = _Backend(
        {
            "status": "ok",
            "diagnostics": [
                {
                    "path": "src/a.ts",
                    "line": 1,
                    "column": 1,
                    "severity": "error",
                    "message": "bad",
                }
            ],
        }
    )
    base = ToolResult(tool_call_id="", success=True, output="已写入 src/a.ts")
    out = await attach_write_diagnostics(base, context=_ctx(backend), path="src/a.ts")
    assert out.success is True
    assert "内环诊断" in out.output
    assert "bad" in out.output
    assert out.display["kind"] == "code_diagnostics"


@pytest.mark.asyncio
async def test_attach_write_diagnostics_failure_keeps_write_success():
    backend = _Backend(raise_exc=RuntimeError("lsp down"))
    base = ToolResult(tool_call_id="", success=True, output="已写入 src/a.ts")
    out = await attach_write_diagnostics(base, context=_ctx(backend), path="src/a.ts")
    assert out.success is True
    assert "内环诊断不可用" in out.output
    assert "lsp down" in out.output


@pytest.mark.asyncio
async def test_attach_write_diagnostics_skips_non_js():
    backend = _Backend()
    base = ToolResult(tool_call_id="", success=True, output="ok")
    out = await attach_write_diagnostics(base, context=_ctx(backend), path="readme.md")
    assert out.output == "ok"
    assert backend.calls == []


@pytest.mark.asyncio
async def test_server_workspace_diagnostics_unavailable(tmp_path, monkeypatch):
    from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult
    from agentcore.workspace.server import ServerWorkspace

    class _Sand:
        async def execute(self, req: ExecutionRequest) -> ExecutionResult:
            raise AssertionError("should not execute")

    ws = ServerWorkspace(tmp_path, _Sand())  # type: ignore[arg-type]
    payload = await ws.diagnostics(["a.ts"])
    assert payload["status"] == "unavailable"
    assert "云端" in payload["reason"]
    assert payload["diagnostics"] == []
