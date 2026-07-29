"""Team-gate for the CEO captain ReAct loop (hard stop after investigation threshold).

Covers investigation trigger, one-shot latch, worker isolation, hard-stop tool
strip, and post-gate long-answer reject. Scripted fake provider — zero LLM.

**不扫用户原文猜意图**分叉（无成篇/改文件/摸底正则路径）；统一硬闸文案。
闸前长文直答仍靠提示词「路由·第一拍」（see test_prompt / _CEO_CORE_HINT）。
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
    assert "5 轮" in text  # 按探路轮计，非同轮并行工具次数
    assert "调查类工具已收回" in text
    assert "delegate" in text
    assert "归类理由" in text
    assert "禁止长文直答" in text
    assert "≥2 角" in text or "2 角" in text
    assert "禁止再搜" in text
    assert "组队意图已明确" not in text
    assert "research_report" not in text  # 不靠正则追加成篇形状句
    assert "广度摸底探路" not in text
    assert "本地改文件" not in text


def test_team_gate_counts_rounds_not_parallel_calls():
    """同轮并行多工具只计 1 轮：calls 再高、rounds<5 不硬闸。"""
    controller = create_loop_controller(frozenset({"search", "git", "file_list"}))
    controller._investigation_calls = 5
    controller._investigation_rounds = 1
    disabled: set[str] = set()
    messages = [LLMMessage(role="user", content="继续完成白板应用开发")]
    assert (
        maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            disabled_tools=disabled,
            investigation_tools=frozenset({"search", "git", "file_list"}),
        )
        is False
    )
    assert disabled == set()
    controller._investigation_rounds = 4
    assert (
        maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            disabled_tools=disabled,
            investigation_tools=frozenset({"search", "git", "file_list"}),
        )
        is False
    )
    controller._investigation_rounds = 5
    assert maybe_inject_team_gate(
        controller,
        messages=messages,
        run_id="r",
        round_idx=0,
        role="captain",
        disabled_tools=disabled,
        investigation_tools=frozenset({"search", "git", "file_list"}),
    )
    assert disabled == {"search", "git", "file_list"}


def test_user_text_does_not_branch_gate_copy():
    """成篇 / 摸底 / 改文件用户话 → 同一套硬闸文案（不扫原文分叉）。"""
    cases = [
        "写一篇起诉第三者立案实务研究报告，4000 字 Markdown 落盘",
        "深度理解 https://github.com/Lawofall/AgentCore 代码",
        "帮我改一下项目根目录的 README.md：加一小节快速开始。",
        "查一下 X 和 Y 的区别",
    ]
    for content in cases:
        controller = create_loop_controller(frozenset({"search"}))
        controller._investigation_rounds = 5
        disabled: set[str] = set()
        messages = [LLMMessage(role="user", content=content)]
        assert maybe_inject_team_gate(
            controller,
            messages=messages,
            run_id="r",
            round_idx=0,
            role="captain",
            disabled_tools=disabled,
            investigation_tools=frozenset({"search"}),
        )
        hard = next(
            m.content or "" for m in messages if "探路已达硬上限" in (m.content or "")
        )
        assert "research_report" not in hard
        assert "成篇调研形状" not in hard
        assert "广度摸底探路" not in hard
        assert "本地改文件" not in hard
        assert disabled == {"search"}


def test_local_edit_does_not_early_gate_on_two_peeks():
    """改 README：本地摸仓 2 次不再单独硬闸（与网页探路同阈）。"""
    tools = frozenset({"file_list", "file_read", "grep", "web_search"})
    controller = create_loop_controller(tools)
    controller._investigation_calls = 2
    controller._investigation_rounds = 2
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


def test_ceo_prompt_d10_repair_routing_rules():
    """CEO 主提示含 D10′ light / repair_code 选型（契约文案，非意图分类器）."""
    from agentcore.runtime.resolve import prompt as prompt_mod

    core = prompt_mod._CEO_CORE_HINT
    assert "单文件/单符号一刀切" in core
    assert "complexity_hint=light" in core
    assert 'playbook="repair_code"' in core
    assert "修码默认" in core
    assert "不扫原文做意图分类" in core
    # 会后修复分流：已有调查批 → continue_from；换 title≠换职能；禁再套 repair_code。
    assert "continue_from_run_id" in core
    assert "换 title" in core or "换职能" in core
    assert "冷开新三角色" in core or "再套" in core


def test_hard_stop_disables_investigation_tools_when_intent_clear():
    controller = create_loop_controller(frozenset({"search", "read_url"}))
    controller._investigation_rounds = 5  # threshold met
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


def test_open_qa_still_hard_stops_at_threshold():
    """开放问答：≥5 轮仍硬收剥工具（无 soft、无意图分叉）。"""
    controller = create_loop_controller(frozenset({"search"}))
    controller._investigation_rounds = 5
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
    # ≥5 investigation rounds → hard gate once; tools stripped so 6th search
    # cannot execute; subsequent rounds stay quiet.
    search = _StubTool(name="search")
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_tool_chunk("search", '{"q": "3"}')],
            [_tool_chunk("search", '{"q": "4"}')],
            [_tool_chunk("search", '{"q": "5"}')],
            [_tool_chunk("search", '{"q": "6"}')],
            [_content_chunk("ok")],
        ]
    )
    content, messages = await _run_captain(provider, _registry(search))

    assert content == "ok"
    gates = _team_gate_msgs(messages)
    assert len(gates) == 1
    assert "探路已达硬上限" in (gates[0].content or "")
    assert search.calls == 5  # hard path stripped tools — 6th must not execute


@pytest.mark.asyncio
async def test_below_investigation_threshold_no_gate():
    # Four calls stay under threshold=5; gate must not fire.
    search = _StubTool(name="search")
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_tool_chunk("search", '{"q": "3"}')],
            [_tool_chunk("search", '{"q": "4"}')],
            [_content_chunk("short answer")],
        ]
    )
    content, messages = await _run_captain(provider, _registry(search))

    assert content == "short answer"
    assert _team_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_no_tool_long_answer_does_not_fire_team_gate():
    """闸前长文不触发 team_gate（无探路轮）；靠提示词第一拍约束。"""
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
    # Post-gate wrap-up uses short prose so direct-reject soft gate stays quiet.
    search = _StubTool(name="search")
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_tool_chunk("search", '{"q": "3"}')],
            [_tool_chunk("search", '{"q": "4"}')],
            [_tool_chunk("search", '{"q": "5"}')],
            [_content_chunk("归类：单点事实。X 与 Y 的差异是超时默认值不同。")],
        ]
    )
    _content, messages = await _run_captain(provider, _registry(search))

    assert len(_team_gate_msgs(messages)) == 1


def test_direct_reject_predicates():
    from agentcore.runtime.engine.governance import (
        TEAM_GATE_DIRECT_REJECT_MIN_CHARS,
        should_team_gate_direct_reject,
        team_gate_direct_reject_prompt,
    )

    prompt = team_gate_direct_reject_prompt()
    assert "禁止长文直答" in prompt
    assert "delegate" in prompt
    assert "归类" in prompt

    c = create_loop_controller(frozenset())
    c.mark_team_gate_fired()
    long = "甲" * TEAM_GATE_DIRECT_REJECT_MIN_CHARS
    assert should_team_gate_direct_reject(c, role="captain", content=long) is True
    # 长文即使自报归类也拒（统一：闸后禁长文）
    assert (
        should_team_gate_direct_reject(
            c, role="captain", content="归类：追问。" + long
        )
        is True
    )
    assert should_team_gate_direct_reject(c, role="captain", content="短") is False


@pytest.mark.asyncio
async def test_post_gate_long_answer_rejected_once():
    """闸后长文 → 丢稿再催；第二次短答放行。"""
    search = _StubTool(name="search")
    long = "甲" * 500
    provider = _ScriptedProvider(
        [
            [_tool_chunk("search", '{"q": "1"}')],
            [_tool_chunk("search", '{"q": "2"}')],
            [_tool_chunk("search", '{"q": "3"}')],
            [_tool_chunk("search", '{"q": "4"}')],
            [_tool_chunk("search", '{"q": "5"}')],
            [_content_chunk(long)],
            [_content_chunk("归类：单点事实。差异在超时默认值。")],
        ]
    )
    content, messages = await _run_captain(provider, _registry(search))

    assert content == "归类：单点事实。差异在超时默认值。"
    assert len(_team_gate_msgs(messages)) == 1
    reject_msgs = [
        m
        for m in messages
        if m.role == "user"
        and m.content
        and "禁止长文直答" in m.content
        and "草稿已丢弃" in m.content
    ]
    assert len(reject_msgs) == 1
