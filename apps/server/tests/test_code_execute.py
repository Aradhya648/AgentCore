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
