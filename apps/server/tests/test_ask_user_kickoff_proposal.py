"""Kickoff proposal-body hard gate: assumptions OR questions required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcore.core.types import ToolEffect
from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.suspension import AskUserSuspension, captain_transcript
from agentcore.tools.builtin.ask_user import AskUserTool
from agentcore.tools.builtin.ask_user.tool import kickoff_requires_proposal_body_error
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx() -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c-kickoff-body",
    )


def _tool(*, message_id: str | None = "m1") -> AskUserTool:
    async def _save(_frame: AskUserSuspension) -> None:
        return None

    async def _drop(_mid: str) -> None:
        return None

    return AskUserTool(
        sink=EventSink(),
        conversation_id="c-kickoff-body",
        timeout_seconds=1.0,
        message_id=message_id,
        suspension_saver=_save if message_id else None,
        suspension_deleter=_drop if message_id else None,
        captain_run_id="cap",
        base_system_prompt="sys",
        user_message="写调研报告",
    )


def _assistant_tool(name: str, args: dict, *, call_id: str) -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id=call_id,
                function=ToolCallFunction(name=name, arguments=json.dumps(args)),
            )
        ],
    )


@pytest.mark.asyncio
async def test_kickoff_message_only_rejected():
    tool = _tool()
    token = captain_transcript.set([LLMMessage(role="user", content="写一份竞品调研报告")])
    try:
        res = await tool.execute({"message": "你是想要简报还是完整报告？"}, _ctx())
    finally:
        captain_transcript.reset(token)

    assert res.success is False
    assert kickoff_requires_proposal_body_error() in (res.error or "")
    assert res.effect is not ToolEffect.SUSPEND
    assert not any(e.type is EventType.CHECKPOINT_REQUIRED for e in tool.sink._history)


@pytest.mark.asyncio
async def test_kickoff_empty_assumptions_and_questions_rejected():
    tool = _tool()
    token = captain_transcript.set([LLMMessage(role="user", content="写调研报告")])
    try:
        res = await tool.execute(
            {"message": "复述目标", "assumptions": [], "questions": []},
            _ctx(),
        )
    finally:
        captain_transcript.reset(token)

    assert res.success is False
    assert kickoff_requires_proposal_body_error() in (res.error or "")


@pytest.mark.asyncio
async def test_kickoff_with_assumptions_passes_gate():
    tool = _tool()
    token = captain_transcript.set([LLMMessage(role="user", content="写一份竞品调研报告")])
    try:
        res = await tool.execute(
            {
                "message": "开工：竞品调研报告",
                "assumptions": [{"label": "篇幅", "value": "约 3k 字"}],
            },
            _ctx(),
        )
    finally:
        captain_transcript.reset(token)

    assert kickoff_requires_proposal_body_error() not in (res.error or "")
    assert res.effect is ToolEffect.SUSPEND


@pytest.mark.asyncio
async def test_kickoff_with_questions_passes_gate():
    tool = _tool()
    token = captain_transcript.set([LLMMessage(role="user", content="写一份竞品调研报告")])
    try:
        res = await tool.execute(
            {
                "message": "开工：竞品调研报告",
                "questions": [
                    {
                        "prompt": "深度",
                        "options": ["简报", "完整报告"],
                        "default": "完整报告",
                    }
                ],
            },
            _ctx(),
        )
    finally:
        captain_transcript.reset(token)

    assert kickoff_requires_proposal_body_error() not in (res.error or "")
    assert res.effect is ToolEffect.SUSPEND


@pytest.mark.asyncio
async def test_decision_message_only_not_tightened():
    """途中 decision 不受提案体硬闸误伤（仅 message 仍可挂起）。"""
    tool = _tool()
    transcript = [
        LLMMessage(role="user", content="先做调研"),
        _assistant_tool("delegate", {"tasks": [{"role": "调研", "task": "摸底"}]}, call_id="d1"),
        LLMMessage(role="tool", content="done", tool_call_id="d1"),
    ]
    token = captain_transcript.set(transcript)
    try:
        res = await tool.execute({"message": "A 还是 B?"}, _ctx())
    finally:
        captain_transcript.reset(token)

    assert kickoff_requires_proposal_body_error() not in (res.error or "")
    assert res.effect is ToolEffect.SUSPEND
    required = next(e for e in tool.sink._history if e.type is EventType.CHECKPOINT_REQUIRED)
    assert required.payload["intent"] == "decision"
