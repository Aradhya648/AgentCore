"""Team-gate for the CEO captain ReAct loop (hard stop after investigation threshold).

Covers investigation trigger, one-shot latch, worker isolation, hard-stop tool
strip, research shape copy, and local-edit threshold. Scripted fake provider —
zero LLM.

long_content post-hoc discard was removed; solo-collapse defense for early long
answers is prompt-side「路由·第一拍」（see test_prompt / _CEO_CORE_HINT）.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentcore.core.types import ToolCategory, ToolEffect
from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, ToolCallDelta
from agentcore.runtime.engine import react_loop
from agentcore.runtime.engine.governance import (
    create_loop_controller,
    maybe_inject_team_gate,
    team_gate_hard_stop_prompt,
    team_gate_local_edit_prompt,
)
from agentcore.runtime.events import EventSink
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.llm_helpers import make_profile_params


def _tool_chunk(name: str, args: str, *, call_id: str = "c") -> LLMChunk:
    return LLMChunk(
        delta_tool_calls=[
            ToolCallDelta(index=0, id=call_id, function_name=name, arguments_delta=args)
        ]
    )


def _content_chunk(text: str) -> LLMChunk:
    return LLMChunk(delta_content=text)


class _ScriptedProvider:
    def __init__(self, rounds: list[list[LLMChunk]]) -> None:
        self._rounds = rounds
        self.calls = 0

    async def stream(self, request):  # noqa: ANN001
        chunks = self._rounds[self.calls] if self.calls < len(self._rounds) else []
        self.calls += 1
        for chunk in chunks:
            yield chunk


class _StubTool:
    def __init__(
        self,
        name: str = "search",
        *,
        category: ToolCategory = ToolCategory.SEARCH,
    ) -> None:
        self._name = name
        self._category = category
        self.calls = 0

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=self._category,
        )

    async def execute(self, arguments, context) -> ToolResult:  # noqa: ANN001
        self.calls += 1
        return ToolResult(
            tool_call_id="",
            success=True,
            output="result",
            effect=ToolEffect.CONTINUE,
        )


def _registry(*tools: _StubTool) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in tools:
        reg.register(tool)
    return reg


def _context() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


def _team_gate_msgs(messages: list[LLMMessage]) -> list[LLMMessage]:
    return [
        m
        for m in messages
        if m.role == "user"
        and m.content
        and "探路已达硬上限" in m.content
    ]


async def _run_captain(
    provider: _ScriptedProvider,
    tools: ToolRegistry,
    *,
    role: str = "captain",
    max_rounds: int = 20,
) -> tuple[str, list[LLMMessage]]:
    messages: list[LLMMessage] = [LLMMessage(role="user", content="go")]
    profile = make_profile_params(max_rounds=max_rounds)
    content, *_ = await react_loop(
        messages=messages,
        llm=provider,
        tools=tools,
        sink=EventSink(),
        tool_context=_context(),
        profile=profile,
        turn_model="m",
        role=role,
    )
    return content, messages


def test_hard_stop_copy_strips_and_steers_delegate():
    text = team_gate_hard_stop_prompt()
    assert "硬上限" in text
    assert "调查类工具已收回" in text
    assert "delegate" in text
    assert "归类理由" in text
    assert "禁止再搜" in text
    assert "组队意图已明确" not in text
    assert "research_report" not in text  # 默认无成篇形状句


def test_team_gate_research_shape_copy_when_flagged():
    hard = team_gate_hard_stop_prompt(research_shape=True)
    assert "成篇调研形状" in hard
    assert "research_report" in hard
    assert "禁止" in hard and "一人" in hard


def test_hard_stop_research_intent_injects_shape():
    controller = create_loop_controller(frozenset({"search", "read_url"}))
    controller._investigation_calls = 3
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content="写一篇起诉第三者立案实务研究报告，4000–6000 字落盘",
        ),
        LLMMessage(role="assistant", content="协作方案与团队分工如下……"),
        LLMMessage(role="user", content="认可"),
    ]
    assert (
        maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            disabled_tools=disabled,
            investigation_tools=frozenset({"search", "read_url"}),
        )
        is True
    )
    gates = [m.content or "" for m in messages if m.role == "user" and "探路已达硬上限" in (m.content or "")]
    assert len(gates) == 1
    assert "research_report" in gates[0]
    assert "成篇调研形状" in gates[0]


def test_soft_gate_non_research_skips_shape():
    """开放问答：≥3 硬收并剥工具，但不追加成篇形状句。"""
    controller = create_loop_controller(frozenset({"search"}))
    controller._investigation_calls = 3
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content="查一下 X 和 Y 的区别")]
    assert maybe_inject_team_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        disabled_tools=disabled,
        investigation_tools=frozenset({"search"}),
    )
    hard = next(m.content or "" for m in messages if "探路已达硬上限" in (m.content or ""))
    assert "research_report" not in hard
    assert "成篇调研形状" not in hard
    assert disabled == {"search"}


def test_research_intent_forces_hard_stop_and_shape():
    """成篇调研意图：闸门走硬停 + 形状句。"""
    controller = create_loop_controller(frozenset({"search", "read_url"}))
    controller._investigation_calls = 3
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content="写一篇起诉第三者立案实务研究报告，4000 字 Markdown 落盘",
        )
    ]
    assert maybe_inject_team_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        disabled_tools=disabled,
        investigation_tools=frozenset({"search", "read_url"}),
    )
    assert disabled == {"search", "read_url"}
    hard = next(m.content or "" for m in messages if "探路已达硬上限" in (m.content or ""))
    assert "research_report" in hard


def test_competitor_compare_intent_forces_hard_stop_and_shape():
    """竞品对比落盘：须硬停卸调查工具 + 成篇形状句。"""
    controller = create_loop_controller(frozenset({"web_search", "read_url"}))
    controller._investigation_calls = 3
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content=(
                "调研一下 Notion、Obsidian、Logseq 三家在个人知识管理上的定位差异，"
                "整理成一份 Markdown 对比表（功能、定价、适合谁），落盘到 research/km-compare.md。"
            ),
        )
    ]
    assert maybe_inject_team_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        disabled_tools=disabled,
        investigation_tools=frozenset({"web_search", "read_url"}),
    )
    assert disabled == {"web_search", "read_url"}
    hard = next(m.content or "" for m in messages if "探路已达硬上限" in (m.content or ""))
    assert "成篇调研形状" in hard
    assert "research_report" in hard


def test_local_edit_prompt_urges_delegate_not_research_shape():
    text = team_gate_local_edit_prompt()
    assert "本地改文件" in text
    assert "delegate" in text
    assert "research_report" not in text


def test_local_file_edit_fires_after_two_local_peeks():
    """改 README：本地摸仓 ≥2 次后硬催派并卸调查工具（阈低于网页独搜）。"""
    tools = frozenset({"file_list", "file_read", "grep", "web_search"})
    controller = create_loop_controller(tools)
    controller._investigation_calls = 2
    controller._local_recon_calls = 2
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content=(
                "帮我改一下项目根目录的 README.md：在最上面加一小节「快速开始」，"
                "写三条安装命令，其余内容别动。"
            ),
        )
    ]
    assert maybe_inject_team_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        disabled_tools=disabled,
        investigation_tools=tools,
    )
    assert disabled == tools
    hard = next(m.content or "" for m in messages if "本地改文件探路已够" in (m.content or ""))
    assert "delegate" in hard
    assert "research_report" not in hard


def test_local_file_edit_below_threshold_no_gate():
    tools = frozenset({"file_list", "file_read"})
    controller = create_loop_controller(tools)
    controller._investigation_calls = 1
    controller._local_recon_calls = 1
    disabled: set[str] = set()
    messages = [
        LLMMessage(
            role="user",
            content="帮我改一下项目根目录的 README.md：加一小节快速开始。",
        )
    ]
    assert (
        maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            disabled_tools=disabled,
            investigation_tools=tools,
        )
        is False
    )
    assert disabled == set()


def test_hard_stop_disables_investigation_tools_when_intent_clear():
    controller = create_loop_controller(frozenset({"search", "read_url"}))
    controller._investigation_calls = 3  # threshold met
    disabled: set[str] = set()
    messages = [
        LLMMessage(role="assistant", content="协作方案与团队分工如下……"),
        LLMMessage(role="user", content="认可"),
    ]
    assert (
        maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            disabled_tools=disabled,
            investigation_tools=frozenset({"search", "read_url"}),
        )
        is True
    )
    assert disabled == {"search", "read_url"}
    assert any("探路已达硬上限" in (m.content or "") for m in messages)


def test_soft_path_keeps_tools_without_team_intent():
    """开放问答无组队意图：≥3 仍硬收剥工具（无 soft）。"""
    controller = create_loop_controller(frozenset({"search"}))
    controller._investigation_calls = 3
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content="查一下 X 和 Y 的区别")]
    assert (
        maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            disabled_tools=disabled,
            investigation_tools=frozenset({"search"}),
        )
        is True
    )
    assert disabled == {"search"}
    assert any("探路已达硬上限" in (m.content or "") for m in messages)


@pytest.mark.asyncio
async def test_investigation_threshold_fires_once_for_captain():
    # ≥3 investigation calls → hard gate once; tools stripped so 4th search
    # cannot execute; subsequent rounds stay quiet.
    search = _StubTool(name="search")
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_tool_chunk("search", '{"q": "3"}')],
            [_tool_chunk("search", '{"q": "4"}')],
            [_content_chunk("ok")],
        ]
    )
    content, messages = await _run_captain(provider, _registry(search))

    assert content == "ok"
    gates = _team_gate_msgs(messages)
    assert len(gates) == 1
    assert "探路已达硬上限" in (gates[0].content or "")
    assert search.calls == 3  # hard path stripped tools — 4th must not execute


@pytest.mark.asyncio
async def test_below_investigation_threshold_no_gate():
    # Two calls stay under threshold=3; gate must not fire.
    search = _StubTool(name="search")
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_content_chunk("short answer")],
        ]
    )
    content, messages = await _run_captain(provider, _registry(search))

    assert content == "short answer"
    assert _team_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_no_tool_long_answer_does_not_fire_team_gate():
    """long_content post-hoc discard removed: early long prose is kept as-is."""
    long = "甲" * 500
    provider = _ScriptedProvider([[_content_chunk(long)]])
    content, messages = await _run_captain(provider, _registry())

    assert content == long
    assert _team_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_no_tool_short_answer_no_gate():
    provider = _ScriptedProvider([[_content_chunk("嗯，好的")]])
    content, messages = await _run_captain(provider, _registry())

    assert content == "嗯，好的"
    assert _team_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_worker_role_never_fires():
    search = _StubTool(name="search")
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_tool_chunk("search", '{"q": "3"}')],
            [_content_chunk("甲" * 500)],
        ]
    )
    content, messages = await _run_captain(
        provider, _registry(search), role="worker"
    )

    assert "甲" in content
    assert _team_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_after_delegate_no_gate():
    # Once delegate has returned, further investigation must not trip the team-gate
    # (post-delegate steers are a separate mechanism).
    search = _StubTool(name="search")
    delegate = _StubTool(name="delegate", category=ToolCategory.ORCHESTRATION)
    provider = _ScriptedProvider(
        [
            [_tool_chunk("delegate", '{"tasks": []}', call_id="d1")],
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_content_chunk("综述")],
        ]
    )
    content, messages = await _run_captain(provider, _registry(search, delegate))

    assert content == "综述"
    assert _team_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_investigation_fires_at_most_once():
    # Investigation gate first; further investigation rounds must not inject again.
    search = _StubTool(name="search")
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_tool_chunk("search", '{"q": "3"}')],
            [_content_chunk("甲" * 500)],
        ]
    )
    _content, messages = await _run_captain(provider, _registry(search))

    assert len(_team_gate_msgs(messages)) == 1
