"""ask_user checkpoint intent resolution（开工提案壳已拆除 → 默认 decision）。"""

import json

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.tools.builtin.ask_user.intent import resolve_ask_checkpoint_intent


def _assistant_tool(name: str, args: dict | None = None, *, call_id: str = "c1") -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content="",
        tool_calls=[
            ToolCall(
                id=call_id,
                function=ToolCallFunction(name=name, arguments=json.dumps(args or {})),
            )
        ],
    )


def test_empty_transcript_is_decision():
    assert resolve_ask_checkpoint_intent(None) == "decision"
    assert resolve_ask_checkpoint_intent([]) == "decision"


def test_opening_turn_without_execution_is_decision():
    transcript = [
        LLMMessage(role="user", content="做个网站"),
        _assistant_tool("consult_skill", {"name": "ask_user_kickoff"}, call_id="cs"),
        LLMMessage(role="tool", content="skill body", tool_call_id="cs"),
        _assistant_tool("ask_user", {"message": "短澄清"}, call_id="ask"),
    ]
    assert resolve_ask_checkpoint_intent(transcript) == "decision"


def test_midtask_skill_consult_is_decision():
    transcript = [
        LLMMessage(role="user", content="继续"),
        _assistant_tool("consult_skill", {"name": "ask_user_midtask"}, call_id="cs"),
        LLMMessage(role="tool", content="skill body", tool_call_id="cs"),
        _assistant_tool("ask_user", {"message": "选 A 还是 B"}, call_id="ask"),
    ]
    assert resolve_ask_checkpoint_intent(transcript) == "decision"


def test_prior_delegate_makes_decision_even_without_skill():
    transcript = [
        LLMMessage(role="user", content="写报告"),
        _assistant_tool("delegate", {"plan": {}}, call_id="del"),
        LLMMessage(role="tool", content="done", tool_call_id="del"),
        _assistant_tool("ask_user", {"message": "终稿提交？"}, call_id="ask"),
    ]
    assert resolve_ask_checkpoint_intent(transcript) == "decision"


def test_second_ask_in_turn_is_decision():
    transcript = [
        LLMMessage(role="user", content="做个 App"),
        _assistant_tool("ask_user", {"message": "短问1"}, call_id="ask1"),
        LLMMessage(role="tool", content="continue", tool_call_id="ask1"),
        _assistant_tool("ask_user", {"message": "途中岔路"}, call_id="ask2"),
    ]
    assert resolve_ask_checkpoint_intent(transcript) == "decision"
