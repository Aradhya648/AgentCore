"""Regression: continue_run contract re-check must load web_seam_scope like cold executor."""

from pathlib import Path

import pytest

from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.executor_continue import continue_run
from agentcore.runtime.runs.session import RunSession
from agentcore.runtime.runs.types import Deliverable, RunPhase, RunSpec
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


class _ContentProvider:
    def __init__(self, content: str) -> None:
        self._content = content

    async def stream(self, request):  # noqa: ANN001
        yield LLMChunk(delta_content=self._content)


def _file_write_transcript() -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="SYS"),
        LLMMessage(role="user", content="验收站点"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(
                    id="w1",
                    function=ToolCallFunction(
                        name="file_write",
                        arguments='{"path": "site/QA.md", "content": "# QA\\n"}',
                    ),
                )
            ],
        ),
        LLMMessage(role="tool", content="已写入 site/QA.md", tool_call_id="w1"),
    ]


@pytest.mark.asyncio
async def test_continue_run_final_web_seam_still_fails_over_threshold(tmp_path: Path):
    """续跑复查须加载 web_seam_scope 整站文件；仅 QA.md 不足以让接缝门禁空转放行。"""
    site = tmp_path / "site"
    site.mkdir()
    orphans = " ".join(f"orph-{i}" for i in range(40))
    (site / "index.html").write_text(
        f'<div class="{orphans} matched"></div>',
        encoding="utf-8",
    )
    (site / "styles.css").write_text(".matched {}", encoding="utf-8")
    (site / "main.js").write_text("// no selectors", encoding="utf-8")
    (site / "QA.md").write_text("# QA\n通过项", encoding="utf-8")

    deliverable = Deliverable(
        form="files",
        requires_files=True,
        artifacts=["site/QA.md"],
        web_seam_scope="site/",
    )
    session = RunSession(
        run_id="qa_1",
        spec=RunSpec(
            run_id="qa_1",
            agent_id="qa_1",
            role="页面 QA",
            task="写 QA 报告",
            deliverable=deliverable,
        ),
        transcript=_file_write_transcript(),
        content="",
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="qa_1",
        agent_id="qa_1",
        backend=ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox()),
        user_id="u",
    )

    state = await continue_run(
        session=session,
        feedback="请补全 QA 报告并提交",
        continuation_run_id="qa_1_retry",
        llm=_ContentProvider("已更新 QA 报告"),
        tools=ToolRegistry(),
        sink=EventSink(),
        base_tool_context=ctx,
        execution_id="e",
    )

    assert state.phase is RunPhase.COMPLETED
    joined = "\n".join(state.warnings or [])
    assert "网页接缝静态检查未通过" in joined or "未命中率" in joined
