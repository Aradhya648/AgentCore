"""Unit tests for run_redirect salvage (热续写门槛)."""

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.runs.salvage import (
    freeze_partial_transcript,
    is_continuable_transcript,
    try_salvage_session,
)
from agentcore.runtime.runs.types import RunSpec


def _spec() -> RunSpec:
    return RunSpec(run_id="r1", task="调研", role="研究员", agent_id="r1", agent_name="研究员")


def test_empty_opening_is_not_continuable():
    msgs = [
        LLMMessage(role="system", content="you are a researcher"),
        LLMMessage(role="user", content="请调研"),
    ]
    assert is_continuable_transcript(msgs) is False
    assert try_salvage_session(spec=_spec(), messages=msgs) is None


def test_assistant_draft_is_continuable():
    msgs = [
        LLMMessage(role="system", content="sys"),
        LLMMessage(role="user", content="task"),
        LLMMessage(role="assistant", content="半成品草稿……"),
    ]
    assert is_continuable_transcript(msgs) is True
    session = try_salvage_session(spec=_spec(), messages=msgs)
    assert session is not None
    assert session.partial is True
    assert session.content == "半成品草稿……"


def test_completed_tool_turn_is_continuable():
    msgs = [
        LLMMessage(role="user", content="task"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(id="c1", function=ToolCallFunction(name="web_search", arguments="{}"))
            ],
        ),
        LLMMessage(role="tool", content="result", tool_call_id="c1"),
    ]
    assert is_continuable_transcript(msgs) is True
    assert try_salvage_session(spec=_spec(), messages=msgs) is not None


def test_incomplete_tool_call_is_truncated():
    msgs = [
        LLMMessage(role="user", content="task"),
        LLMMessage(role="assistant", content="先搜一下"),
        LLMMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ToolCall(id="c1", function=ToolCallFunction(name="web_search", arguments="{}"))
            ],
        ),
    ]
    frozen = freeze_partial_transcript(msgs)
    assert frozen[-1].role == "assistant"
    assert frozen[-1].content == "先搜一下"
    assert is_continuable_transcript(frozen) is True


def test_none_messages_cannot_salvage():
    assert try_salvage_session(spec=_spec(), messages=None) is None
    assert try_salvage_session(spec=_spec(), messages=[]) is None
