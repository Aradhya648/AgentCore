"""辩手两阶段发言管线自测（per-PR 零真实 LLM）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from agentcore.llm.profiles import ProfileParams
from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, LLMResponse, TokenUsage
from agentcore.runtime.debate.speech_pipeline import (
    build_draft_user,
    research_continuation_message,
    research_then_draft,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


@dataclass
class _FakeSink:
    events: list = field(default_factory=list)

    def emit(self, event) -> None:  # noqa: ANN001
        self.events.append(event)


class _DraftOnlyLLM:
    """仅支持 stream 成稿（无工具）。"""

    def __init__(self, speech: str) -> None:
        self.speech = speech
        self.stream_calls = 0

    async def complete(self, request):  # noqa: ANN001
        return LLMResponse(content=self.speech)

    async def stream(self, request):  # noqa: ANN001
        self.stream_calls += 1
        assert request.tools is None
        assert len(request.messages) == 2
        assert request.messages[0].role == "system"
        assert "证据笔记" in (request.messages[1].content or "")
        yield LLMChunk(delta_content=self.speech)
        yield LLMChunk(
            finish_reason="stop", usage=TokenUsage(input_tokens=10, output_tokens=5)
        )


def _ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="r1",
        agent_id="r1",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


def test_build_draft_user_includes_notes_and_brief():
    user = build_draft_user("请立论。", "- 事实 A【已核实·合成】")
    assert "发言任务" in user
    assert "请立论。" in user
    assert "事实 A" in user


def test_research_continuation_asks_for_notes():
    msg = research_continuation_message("为本轮取证")
    assert msg.role == "user"
    assert "证据笔记" in (msg.content or "")


def test_draft_only_skips_research_and_streams_speech():
    """allow_research=False → 单次成稿；发言进 messages。"""
    llm = _DraftOnlyLLM("### 成本可控\n降本可核实。")
    sink = _FakeSink()
    messages = [
        LLMMessage(role="system", content="你是辩手"),
        LLMMessage(role="user", content="旧现场"),
    ]
    speech, _reasoning, usage, rounds = asyncio.run(
        research_then_draft(
            messages,
            llm=llm,
            tools=ToolRegistry(),
            sink=sink,  # type: ignore[arg-type]
            tool_ctx=_ctx(),
            profile=ProfileParams(temperature=0.4, max_rounds=4, name="agent"),
            turn_model="fake",
            allowed_tools=[],
            run_id="r1",
            agent_id="r1",
            citation_sink=[],
            approval_gate=None,
            draft_system="成稿系统\n【输出纪律·禁止前言】",
            draft_brief="请输出结辩。",
            allow_research=False,
        )
    )
    assert speech.startswith("### 成本可控")
    assert llm.stream_calls == 1
    assert rounds == 1
    assert usage.output_tokens == 5
    assert messages[-1].role == "assistant"
    assert messages[-1].content == speech
    assert sink.events  # 至少发过 run_output_delta
