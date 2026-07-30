"""Tests for the code_execute tool's structured display (工具结果富渲染).

The tool flattens stdout/stderr/exit_code into the model-facing ``output`` string,
but also carries them STRUCTURED on ``display`` so the desktop renders a terminal
view (stderr in red, exit-code badge) instead of parsing "stdout:\\n…" text. A
non-zero exit must still produce a display (so a failed run surfaces its stderr).
"""

from agentcore.tools.builtin.code_execute import CodeExecuteTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult


class _FakeBackend:
    """A workspace backend stub whose ``execute`` returns a canned result."""

    def __init__(self, result: ExecutionResult) -> None:
        self._result = result
        self.requests: list[ExecutionRequest] = []

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return self._result


def _ctx(backend: _FakeBackend, on_phase=None) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=backend,  # type: ignore[arg-type]
        user_id="u",
        on_phase=on_phase,
    )


async def test_code_execute_display_carries_stdout_and_exit():
    backend = _FakeBackend(
        ExecutionResult(success=True, stdout="hello\n", stderr="", exit_code=0, duration_ms=5)
    )
    result = await CodeExecuteTool().execute(
        {"code": "print('hello')", "language": "python"}, _ctx(backend)
    )

    assert result.success is True
    assert result.display == {
        "stdout": "hello\n",
        "stderr": "",
        "exit_code": 0,
        "language": "python",
    }


async def test_code_execute_emits_executing_phase():
    # 工具执行阶段进度 (联网前端展示优化): code_execute signals 「正在执行」before the (slow,
    # blocking) sandbox run so the waiting row is live instead of a dead spinner.
    backend = _FakeBackend(
        ExecutionResult(success=True, stdout="ok\n", stderr="", exit_code=0, duration_ms=5)
    )
    phases: list[str] = []
    result = await CodeExecuteTool().execute(
        {"code": "print('ok')", "language": "python"},
        _ctx(backend, on_phase=phases.append),
    )

    assert result.success is True
    assert phases == ["executing"]


async def test_code_execute_surfaces_written_back_files():
    # 产物写回 (gVisor copy-out): the model must see exactly which files landed in
    # the workspace (so it references real paths), and the display carries them for
    # the client. Skipped-by-cap files are disclosed, never silent.
    backend = _FakeBackend(
        ExecutionResult(
            success=True,
            stdout="done\n",
            stderr="",
            exit_code=0,
            duration_ms=5,
            written_files=["out/course.pptx", "out/chart.png"],
            write_back_skipped=1,
        )
    )
    result = await CodeExecuteTool(location="server").execute(
        {"code": "make()", "language": "python"}, _ctx(backend)
    )

    assert result.success is True
    assert "已写回工作区：out/course.pptx、out/chart.png" in result.output
    assert "1 个文件超出写回限额" in result.output
    assert result.display is not None
    assert result.display["written_files"] == ["out/course.pptx", "out/chart.png"]


async def test_code_execute_display_unchanged_without_write_back():
    # No written files → no extra display key (old fixtures stay byte-identical).
    backend = _FakeBackend(
        ExecutionResult(success=True, stdout="ok\n", stderr="", exit_code=0, duration_ms=5)
    )
    result = await CodeExecuteTool().execute(
        {"code": "print('ok')", "language": "python"}, _ctx(backend)
    )
    assert result.display is not None
    assert "written_files" not in result.display
    assert "已写回工作区" not in result.output
    assert "agentcore:written_files" not in result.output


async def test_code_execute_output_carries_structured_write_back_marker():
    # 结构化写回通道 (files_touched 事实口径): besides the human「已写回工作区」line, the
    # output carries a machine-readable JSON marker so files_touched_from_transcript can
    # count the landing WITHOUT parsing the prose — robust even when a filename contains
    # the「、」separator the prose line joins on (which would break naive splitting).
    from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
    from agentcore.runtime.runs.serialize import files_touched_from_transcript

    backend = _FakeBackend(
        ExecutionResult(
            success=True,
            stdout="done\n",
            stderr="",
            exit_code=0,
            duration_ms=5,
            written_files=["out/a、b.md", "out/chart.png"],
        )
    )
    result = await CodeExecuteTool(location="server").execute(
        {"code": "make()", "language": "python"}, _ctx(backend)
    )
    assert "<!--agentcore:written_files:" in result.output
    # The produced marker round-trips through the run's files_touched harvest exactly —
    # including the「、」filename that the human prose line cannot be split on safely.
    transcript = [
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="c1",
                    function=ToolCallFunction(name="code_execute", arguments="{}"),
                )
            ],
        ),
        LLMMessage(role="tool", content=result.output, tool_call_id="c1"),
    ]
    assert files_touched_from_transcript(transcript) == ["out/a、b.md", "out/chart.png"]


async def test_code_execute_display_on_failure_keeps_stderr_and_exit():
    backend = _FakeBackend(
        ExecutionResult(
            success=False,
            stdout="",
            stderr="Traceback (most recent call last):\nNameError: name 'boom'",
            exit_code=1,
            duration_ms=5,
        )
    )
    result = await CodeExecuteTool().execute({"code": "boom", "language": "python"}, _ctx(backend))

    assert result.success is False
    assert result.display is not None
    assert result.display["exit_code"] == 1
    assert "NameError" in result.display["stderr"]
    assert result.display["language"] == "python"


def test_long_running_command_match_catches_dev_servers():
    from agentcore.tools.builtin.code_execute import long_running_command_match

    assert long_running_command_match("npm run dev") is not None
    assert long_running_command_match("pnpm dev") is not None
    assert long_running_command_match("npx vite") is not None
    assert long_running_command_match("os.system('npm run start')") is not None
    # Finite / lookalike — must not trip the gate.
    assert long_running_command_match("npm install") is None
    assert long_running_command_match("npm run build") is None
    assert long_running_command_match("npm run development") is None
    assert long_running_command_match("import { defineConfig } from 'vite'") is None


def test_project_verify_command_match_routes_to_test_run():
    from agentcore.tools.builtin.code_execute import project_verify_command_match

    assert project_verify_command_match("npm install") is not None
    assert project_verify_command_match("pnpm install") is not None
    assert project_verify_command_match("npx tsc --noEmit") is not None
    assert project_verify_command_match("tsc --noEmit") is not None
    assert project_verify_command_match("npm run build") is not None
    assert project_verify_command_match("npm test") is not None
    assert project_verify_command_match("pytest tests/") is not None
    # Short / lookalike — must not trip.
    assert project_verify_command_match("print(1+1)") is None
    assert project_verify_command_match("import { defineConfig } from 'vite'") is None
    assert project_verify_command_match("from 'vitest'") is None
    assert project_verify_command_match("npm run dev") is None  # long_running owns this


async def test_code_execute_blocks_project_verify_without_sandbox():
    backend = _FakeBackend(
        ExecutionResult(success=True, stdout="should-not-run\n", stderr="", exit_code=0, duration_ms=1)
    )
    result = await CodeExecuteTool(location="local").execute(
        {"code": "npx tsc --noEmit", "language": "bash"},
        _ctx(backend),
    )

    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata.get("code") == "project_verify_redirect"
    err = result.error or ""
    assert "test_run" in err
    assert "code_execute" in err
    assert backend.requests == []


async def test_code_execute_blocks_npm_install_to_test_run():
    backend = _FakeBackend(
        ExecutionResult(success=True, stdout="should-not-run\n", stderr="", exit_code=0, duration_ms=1)
    )
    result = await CodeExecuteTool(location="server").execute(
        {"code": "npm install", "language": "bash"},
        _ctx(backend),
    )

    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata.get("code") == "project_verify_redirect"
    assert "test_run" in (result.error or "")
    assert backend.requests == []


async def test_code_execute_blocks_long_running_without_sandbox():
    backend = _FakeBackend(
        ExecutionResult(success=True, stdout="should-not-run\n", stderr="", exit_code=0, duration_ms=1)
    )
    result = await CodeExecuteTool(location="local").execute(
        {"code": "npm run dev", "language": "bash"},
        _ctx(backend),
    )

    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata.get("code") == "long_running_redirect"
    assert "terminal" in (result.error or "")
    assert "wait_for" in (result.error or "")
    assert backend.requests == []


async def test_code_execute_long_running_server_message_has_no_terminal():
    backend = _FakeBackend(
        ExecutionResult(success=True, stdout="", stderr="", exit_code=0, duration_ms=1)
    )
    result = await CodeExecuteTool(location="server").execute(
        {"code": "next dev", "language": "bash"},
        _ctx(backend),
    )

    assert result.success is False
    assert result.contract_failure is True
    err = result.error or ""
    assert "无本机 terminal" in err
    assert "subcommand=start" not in err
    assert backend.requests == []


async def test_code_execute_launcher_unavailable_is_contract_failure():
    """Missing/rejected launcher (exit 127) must not burn the circuit breaker."""
    backend = _FakeBackend(
        ExecutionResult(
            success=False,
            stdout="",
            stderr=(
                "代码执行环境启动失败：找不到可用的命令 'bash'。"
                " 本机没有可用的 bash（Windows 上 PATH 的 bash 常是不可用的 WSL 蹦床）。"
                "请改用 language=javascript 或 python 直接跑代码，不要用 bash 外壳包一层。"
            ),
            exit_code=127,
            duration_ms=1,
        )
    )
    result = await CodeExecuteTool(location="local").execute(
        {"code": "print(42)", "language": "bash"},
        _ctx(backend),
    )

    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata.get("code") == "launcher_unavailable"
    assert result.display is not None
    assert result.display["exit_code"] == 127


async def test_code_execute_nonzero_exit_without_launcher_msg_not_contract():
    """Ordinary script failure (e.g. exit 1) must still count toward the breaker."""
    backend = _FakeBackend(
        ExecutionResult(
            success=False,
            stdout="",
            stderr="Error: fail",
            exit_code=1,
            duration_ms=5,
        )
    )
    result = await CodeExecuteTool().execute(
        {"code": "throw new Error('fail')", "language": "javascript"},
        _ctx(backend),
    )
    assert result.success is False
    assert result.contract_failure is False
    assert result.metadata == {}
