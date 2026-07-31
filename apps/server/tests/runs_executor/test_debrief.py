"""完工交接简报 (debrief) harvest — read a worker's brief off its ``handoff`` tool call.

The brief is STRUCTURED data submitted via the terminal ``handoff`` tool, so it is read straight
off the call's arguments (never parsed back out of markdown prose — its former, fragile form). The
harvester is best-effort and PURE: a transcript with no ``handoff`` call round-trips to ``None`` so
a worker that finished with a plain no-tool answer simply carries no debrief (the deliverable stands
alone).
"""

from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.runs.serialize import debrief_from_transcript


def _handoff(arguments: str, call_id: str = "h1") -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(id=call_id, function=ToolCallFunction(name="handoff", arguments=arguments))
        ],
    )


def _call(name: str, arguments: str, call_id: str = "c1") -> LLMMessage:
    return LLMMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(id=call_id, function=ToolCallFunction(name=name, arguments=arguments))
        ],
    )


def test_parses_all_four_fields():
    transcript = [
        LLMMessage(role="user", content="做事"),
        LLMMessage(role="assistant", content="这是交付正文。"),
        _handoff(
            '{"summary": "完成了登录接口重构", '
            '"key_points": ["响应从 800ms 降到 120ms", "改动 auth/login.py"], '
            '"assumptions": "沿用现有 JWT 方案", '
            '"next_steps": "给注册接口做同样的缓存改造"}'
        ),
        LLMMessage(role="tool", content="已收尾并提交交接简报。", tool_call_id="h1"),
    ]
    debrief = debrief_from_transcript(transcript)
    assert debrief == {
        "summary": "完成了登录接口重构",
        "key_points": ["响应从 800ms 降到 120ms", "改动 auth/login.py"],
        "assumptions": "沿用现有 JWT 方案",
        "next_steps": "给注册接口做同样的缓存改造",
    }


def test_no_handoff_call_returns_none():
    # A worker that finished with a plain no-tool answer carries no debrief.
    transcript = [
        LLMMessage(role="user", content="做事"),
        LLMMessage(role="assistant", content="纯交付正文，没有调用 handoff。"),
    ]
    assert debrief_from_transcript(transcript) is None


def test_other_tool_calls_are_ignored():
    transcript = [
        _call("web_search", '{"query": "x"}'),
        _call("escalate", '{"question": "Y?"}', call_id="c2"),
    ]
    assert debrief_from_transcript(transcript) is None


def test_last_valid_handoff_wins():
    # A re-worked / revised run may submit more than once — the final brief is authoritative.
    transcript = [
        _handoff('{"summary": "第一版结论"}', call_id="h1"),
        LLMMessage(role="user", content="改一下"),
        _handoff('{"summary": "以最后这版为准"}', call_id="h2"),
    ]
    assert debrief_from_transcript(transcript) == {"summary": "以最后这版为准"}


def test_optional_fields_omitted_when_absent():
    assert debrief_from_transcript([_handoff('{"summary": "只给了结论一条"}')]) == {
        "summary": "只给了结论一条"
    }


def test_key_points_only_no_summary():
    # Parity with the old parser: a brief may carry key_points without a summary.
    debrief = debrief_from_transcript([_handoff('{"key_points": ["要点一", "要点二"]}')])
    assert debrief == {"key_points": ["要点一", "要点二"]}


def test_lone_string_key_points_is_tolerated():
    debrief = debrief_from_transcript([_handoff('{"summary": "S", "key_points": "单条要点"}')])
    assert debrief == {"summary": "S", "key_points": ["单条要点"]}


def test_markdown_list_key_points_are_split():
    """Models often emit key_points as a markdown bullet string — harvest splits it."""
    raw = (
        '{"summary": "S", "key_points": "- 响应降到 120ms\\n- 改动 auth/login.py\\n'
        '- 未覆盖边缘路径"}'
    )
    debrief = debrief_from_transcript([_handoff(raw)])
    assert debrief == {
        "summary": "S",
        "key_points": ["响应降到 120ms", "改动 auth/login.py", "未覆盖边缘路径"],
    }


def test_json_array_string_key_points_still_parsed():
    debrief = debrief_from_transcript(
        [_handoff('{"summary": "S", "key_points": "[\\"a\\", \\"b\\"]"}')]
    )
    assert debrief == {"summary": "S", "key_points": ["a", "b"]}


def test_blank_key_points_entries_dropped():
    debrief = debrief_from_transcript(
        [_handoff('{"summary": "S", "key_points": ["有内容", "   ", ""]}')]
    )
    assert debrief == {"summary": "S", "key_points": ["有内容"]}


def test_malformed_arguments_skipped():
    assert debrief_from_transcript([_handoff("not json")]) is None


def test_empty_handoff_degrades_to_none():
    # A handoff with no usable field carries nothing → None (the deliverable stands alone).
    assert debrief_from_transcript([_handoff("{}")]) is None
    assert debrief_from_transcript([_handoff('{"summary": "   "}')]) is None
