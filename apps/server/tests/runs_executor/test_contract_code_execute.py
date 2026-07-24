"""交付事实口径 (executor wiring): a worker that lands its deliverable ONLY through
``code_execute`` (sandbox copy-out) satisfies ``requires_files`` — no wasted rewrite
forcing it to regenerate the whole product via ``file_write``.

Reproduces the collab-graph waste: the product really landed (staging write-back), a
downstream worker read it, but ``requires_files`` counted only ``file_write`` intents
and failed — burning a multi-thousand-token regeneration. The structured write-back
channel makes the landing a fact the gate honours (and the CEO manifest inherits it);
a pure-prose finish that lands nothing still fails, so the gate is not loosened.
"""

import json

from agentcore.llm.provider.protocol import LLMChunk, ToolCallDelta
from agentcore.runtime.delegate.completion import collect_delivered_files
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.executor import build_agent_executor
from agentcore.runtime.runs.types import RunPhase
from agentcore.runtime.runs.wave import WaveScheduler
from agentcore.tools.builtin.code_execute import CodeExecuteTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.protocol import ExecutionResult
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.runs_executor.conftest import _ContentProvider, _ctx


class _CopyOutBackend:
    """Wraps a real ServerWorkspace; its ``execute`` simulates the gVisor copy-out path:
    write the artifact into the workspace AND report it on ``written_files``.

    A real ``SubprocessSandbox`` writes the workspace directly with ``written_files=None``
    — which would hide the landing from the transcript harvest. This reproduces the cloud
    copy-out semantics the structured write-back channel exists for. Everything else
    (``index_files`` / ``write`` / ``location`` …) delegates to the inner workspace.
    """

    def __init__(self, inner, artifacts: dict[str, str]) -> None:  # noqa: ANN001
        self._inner = inner
        self._artifacts = artifacts

    async def execute(self, request):  # noqa: ANN001
        for path, content in self._artifacts.items():
            await self._inner.write(path, content)
        return ExecutionResult(
            success=True,
            stdout="done\n",
            stderr="",
            exit_code=0,
            duration_ms=5,
            written_files=list(self._artifacts.keys()),
        )

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class _CodeExecuteThenNote:
    """Round 1: call ``code_execute`` (lands the file via copy-out); round 2: stream a
    terse chat note — the product is on disk, deliberately NOT pasted into the reply."""

    def __init__(self, code: str, note: str) -> None:
        self._rounds = [
            [
                LLMChunk(
                    delta_tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="x1",
                            function_name="code_execute",
                            arguments_delta=json.dumps(
                                {"code": code, "language": "python"}, ensure_ascii=False
                            ),
                        )
                    ]
                )
            ],
            [LLMChunk(delta_content=note)],
        ]
        self.calls = 0

    async def stream(self, request):  # noqa: ANN001
        chunks = (
            self._rounds[self.calls]
            if self.calls < len(self._rounds)
            else [LLMChunk(delta_content="done")]
        )
        self.calls += 1
        for chunk in chunks:
            yield chunk


async def test_requires_files_satisfied_by_code_execute_landing(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    backend = _CopyOutBackend(
        ServerWorkspace(root=root, sandbox=SubprocessSandbox()),
        {"report.md": "# 报告\n扎实可信的分析正文。"},
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=backend,  # type: ignore[arg-type]
        user_id="u",
    )
    plan, _ = build_run_plan(
        [
            {
                "role": "分析",
                "task": "跑脚本生成报告并落盘",
                "deliverable": {"requires_files": True},
            }
        ],
        id_prefix="t",
    )
    reg = ToolRegistry()
    reg.register(CodeExecuteTool(location="server"))
    provider = _CodeExecuteThenNote(
        "open('report.md', 'w').write('done')", "报告已生成，见 report.md"
    )
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=reg,
        sink=EventSink(),
        base_tool_context=ctx,
        system_prompt="SYS",
        user_message="req",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    state = res["t_1"]
    assert state.phase is RunPhase.COMPLETED
    # requires_files satisfied by the code_execute landing → no contract shortfall / retry.
    assert state.warnings == []
    assert provider.calls == 2  # no wasted regenerate-via-file_write round
    assert state.files_touched == ["report.md"]
    # CEO handoff manifest (collect_delivered_files reads files_touched) inherits it.
    assert collect_delivered_files(res) == ["report.md"]


async def test_requires_files_still_fails_on_pure_prose_no_landing():
    # No code_execute, no file_write — the product is only prose. A strict requires_files
    # deliverable still hard-fails, proving the gate was not loosened.
    plan, _ = build_run_plan(
        [
            {
                "role": "分析",
                "task": "生成报告并落盘",
                "deliverable": {"requires_files": True, "strict": True},
            }
        ],
        id_prefix="t",
    )
    provider = _ContentProvider(["我把整份报告贴在这里……", "还是只有正文没有落盘……"])
    executor = build_agent_executor(
        plan=plan,
        llm=provider,
        tools=ToolRegistry(),
        sink=EventSink(),
        base_tool_context=_ctx(),
        system_prompt="SYS",
        user_message="req",
        execution_id="e",
    )
    res = await WaveScheduler().run(plan, executor)
    state = res["t_1"]
    assert state.phase is RunPhase.FAILED
    assert "工作区" in state.error
