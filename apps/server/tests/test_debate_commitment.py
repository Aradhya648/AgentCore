"""Soft debate-commitment gate: user picked a debate form on kickoff, CEO must honor it.

Acceptance:
- selected debate, never ran → inject guided nudge once on wrap-up
- debate already executed → pass through
- user never explicitly picked a form → no intervene
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcore.core.types import ToolCategory, ToolEffect
from agentcore.llm.provider.protocol import (
    LLMChunk,
    LLMMessage,
    ToolCall,
    ToolCallDelta,
    ToolCallFunction,
)
from agentcore.runtime.engine import react_loop
from agentcore.runtime.engine.debate_commitment import (
    debate_gate_nudge_prompt,
    user_selected_debate_form,
)
from agentcore.runtime.engine.governance import (
    maybe_inject_debate_gate,
    should_debate_gate,
)
from agentcore.runtime.events import EventSink
from agentcore.runtime.loop_controller import LoopController
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.llm_helpers import make_profile_params

_SETTLED_AFFIRM = (
    "用户答复：\n"
    "就按这个方案开做：\n"
    "· 辩论环节采用哪种形式？：辩论（正反攻防）\n"
    "请据此继续。"
)
_SETTLED_DECLINE = (
    "用户答复：\n"
    "就按这个方案开做：\n"
    "· 辩论环节采用哪种形式？：不需要辩论环节\n"
    "请据此继续。"
)


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
        name: str = "debate",
        *,
        category: ToolCategory = ToolCategory.ORCHESTRATION,
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
            output="debate done" if self._name == "debate" else "ok",
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


def _debate_gate_msgs(messages: list[LLMMessage]) -> list[LLMMessage]:
    return [
        m
        for m in messages
        if m.role == "user" and m.content and "辩论承诺复核" in m.content
    ]


def _kickoff_messages(*, settled: str) -> list[LLMMessage]:
    return [
        LLMMessage(role="user", content="开干"),
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="ask1",
                    function=ToolCallFunction(
                        name="ask_user",
                        arguments=json.dumps(
                            {
                                "questions": [
                                    {
                                        "prompt": "辩论环节采用哪种形式？",
                                        "default": "辩论（正反攻防）",
                                        "options": [
                                            {"label": "辩论（正反攻防）"},
                                            {"label": "不需要辩论环节"},
                                        ],
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            ],
        ),
        LLMMessage(role="tool", tool_call_id="ask1", content=settled),
    ]


async def _run_captain(
    provider: _ScriptedProvider,
    tools: ToolRegistry,
    *,
    messages: list[LLMMessage] | None = None,
    role: str = "captain",
    max_rounds: int = 20,
) -> tuple[str, list[LLMMessage]]:
    msgs = messages if messages is not None else [LLMMessage(role="user", content="go")]
    profile = make_profile_params(max_rounds=max_rounds)
    content, *_ = await react_loop(
        messages=msgs,
        llm=provider,
        tools=tools,
        sink=EventSink(),
        tool_context=_context(),
        profile=profile,
        turn_model="m",
        role=role,
    )
    return content, msgs


def test_nudge_copy_guides_honor_or_explain():
    text = debate_gate_nudge_prompt()
    assert "辩论承诺复核" in text
    assert "`debate`" in text
    assert "豁免理由" in text
    assert "不阻断收尾" in text


def test_user_selected_debate_form_from_desktop_note():
    assert user_selected_debate_form(
        [LLMMessage(role="tool", tool_call_id="x", content=_SETTLED_AFFIRM)]
    )
    assert not user_selected_debate_form(
        [LLMMessage(role="tool", tool_call_id="x", content=_SETTLED_DECLINE)]
    )
    assert not user_selected_debate_form(
        [LLMMessage(role="tool", tool_call_id="x", content="用户答复：随便做就行\n请据此继续。")]
    )


def test_user_selected_debate_form_honors_card_default_on_bare_confirm():
    args = json.dumps(
        {
            "questions": [
                {
                    "prompt": "辩论环节采用哪种形式？",
                    "default": "辩论（正反攻防）",
                    "options": [{"label": "辩论（正反攻防）"}, {"label": "不需要辩论环节"}],
                }
            ]
        },
        ensure_ascii=False,
    )
    messages = [
        LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="ask1",
                    function=ToolCallFunction(name="ask_user", arguments=args),
                )
            ],
        ),
        LLMMessage(
            role="tool",
            tool_call_id="ask1",
            content="用户确认：按你提出的方向继续。",
        ),
    ]
    assert user_selected_debate_form(messages)


def test_should_debate_gate_respects_latches():
    controller = LoopController()
    messages = [LLMMessage(role="tool", tool_call_id="x", content=_SETTLED_AFFIRM)]
    assert should_debate_gate(controller, role="captain", messages=messages)
    controller.mark_debate_executed()
    assert not should_debate_gate(controller, role="captain", messages=messages)

    controller2 = LoopController()
    controller2.mark_debate_gate_fired()
    assert not should_debate_gate(controller2, role="captain", messages=messages)
    assert not should_debate_gate(LoopController(), role="worker", messages=messages)


def test_maybe_inject_debate_gate_one_shot():
    controller = LoopController()
    messages = [LLMMessage(role="tool", tool_call_id="x", content=_SETTLED_AFFIRM)]
    assert maybe_inject_debate_gate(
        controller, messages=messages, run_id="r", round_idx=0, role="captain"
    )
    assert controller.debate_gate_fired
    assert len(_debate_gate_msgs(messages)) == 1
    assert not maybe_inject_debate_gate(
        controller, messages=messages, run_id="r", round_idx=1, role="captain"
    )
    assert len(_debate_gate_msgs(messages)) == 1


@pytest.mark.asyncio
async def test_selected_debate_not_executed_injects_nudge():
    """选了 debate 未执行 → 收尾注入引导，允许下一轮说明后放行。"""
    provider = _ScriptedProvider(
        [
            [_content_chunk("汇总已含论证，直接收官。")],
            [_content_chunk("已向用户说明豁免理由后的最终交付")],
        ]
    )
    content, messages = await _run_captain(
        provider,
        _registry(_StubTool(name="debate")),
        messages=_kickoff_messages(settled=_SETTLED_AFFIRM),
    )

    assert content == "已向用户说明豁免理由后的最终交付"
    gates = _debate_gate_msgs(messages)
    assert len(gates) == 1
    assert "`debate`" in (gates[0].content or "")


@pytest.mark.asyncio
async def test_debate_executed_passes_through():
    """已执行 debate → 正常放行，不注入。"""
    provider = _ScriptedProvider(
        [
            [
                _tool_chunk(
                    "debate",
                    '{"motion":"X","form":"debate","sides":[]}',
                    call_id="d1",
                )
            ],
            [_content_chunk("辩论后综述")],
        ]
    )
    content, messages = await _run_captain(
        provider,
        _registry(_StubTool(name="debate")),
        messages=_kickoff_messages(settled=_SETTLED_AFFIRM),
    )

    assert content == "辩论后综述"
    assert _debate_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_no_explicit_form_selection_no_intervene():
    """用户未显式选协作形式 → 不干预。"""
    provider = _ScriptedProvider([[_content_chunk("直接交付")]])
    content, messages = await _run_captain(
        provider,
        _registry(_StubTool(name="debate")),
        messages=[LLMMessage(role="user", content="随便聊聊")],
    )

    assert content == "直接交付"
    assert _debate_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_decline_form_no_intervene():
    """开工卡上明确不要辩论 → 不注入。"""
    provider = _ScriptedProvider([[_content_chunk("无辩论交付")]])
    content, messages = await _run_captain(
        provider,
        _registry(_StubTool(name="debate")),
        messages=_kickoff_messages(settled=_SETTLED_DECLINE),
    )

    assert content == "无辩论交付"
    assert _debate_gate_msgs(messages) == []


@pytest.mark.asyncio
async def test_worker_role_never_fires():
    provider = _ScriptedProvider([[_content_chunk("工人收尾")]])
    content, messages = await _run_captain(
        provider,
        _registry(_StubTool(name="debate")),
        messages=_kickoff_messages(settled=_SETTLED_AFFIRM),
        role="worker",
    )

    assert content == "工人收尾"
    assert _debate_gate_msgs(messages) == []
