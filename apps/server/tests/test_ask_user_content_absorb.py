"""Unit tests for blocking ask_user content absorption."""

import json

from agentcore.core.types import ToolEffect
from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime.engine.ask_user_absorb import (
    absorb_blocking_ask_user_content,
    prepare_blocking_ask_user_tool_calls,
)
from agentcore.runtime.facts import FactKind, LlmCallFact, TurnFactLog, current_fact_log
from agentcore.runtime.loop_controller import ToolAttempt


def _ask_user_call(*, message: str = "", blocking: bool | None = None) -> ToolCall:
    args: dict = {}
    if message:
        args["message"] = message
    if blocking is not None:
        args["blocking"] = blocking
    return ToolCall(
        id="call_ask",
        function=ToolCallFunction(name="ask_user", arguments=json.dumps(args)),
    )


def test_prepare_injects_round_content_when_message_empty():
    calls = prepare_blocking_ask_user_tool_calls(
        [_ask_user_call()],
        "帮你分析一下选项：",
    )
    args = json.loads(calls[0].function.arguments)
    assert args["message"] == "帮你分析一下选项："


def test_prepare_leaves_explicit_message():
    calls = prepare_blocking_ask_user_tool_calls(
        [_ask_user_call(message="卡片文案")],
        "正文铺垫",
    )
    args = json.loads(calls[0].function.arguments)
    assert args["message"] == "卡片文案"


def test_prepare_skips_non_blocking():
    calls = prepare_blocking_ask_user_tool_calls(
        [_ask_user_call(blocking=False)],
        "继续推进",
    )
    args = json.loads(calls[0].function.arguments)
    assert "message" not in args


def test_absorb_clears_assistant_content_and_journal_on_suspend():
    log = TurnFactLog()
    log.record_fact(
        LlmCallFact(
            run_id="cap",
            round_idx=0,
            content="正文铺垫",
            tool_calls=[
                {
                    "id": "call_ask",
                    "type": "function",
                    "function": {"name": "ask_user", "arguments": '{"message": "卡片"}'},
                }
            ],
        ).to_fact()
    )
    messages = [
        LLMMessage(role="user", content="?"),
        LLMMessage(
            role="assistant",
            content="正文铺垫",
            tool_calls=[_ask_user_call(message="卡片")],
        ),
    ]
    resets: list[str] = []

    token = current_fact_log.set(log)
    try:
        absorbed = absorb_blocking_ask_user_content(
            messages=messages,
            tool_calls=[_ask_user_call(message="卡片")],
            attempts=[ToolAttempt("fp", "ask_user", True)],
            terminal_effect=ToolEffect.SUSPEND,
            emit_reset=resets.append,
        )
    finally:
        current_fact_log.reset(token)

    assert absorbed is True
    assert messages[-1].content is None
    # 吸收发一次 reset，reason=ask_user（不折「已按交付规范重写」chip）。
    assert resets == ["ask_user"]
    llm_facts = [f for f in log.entries() if f["kind"] == FactKind.LLM_CALL.value]
    assert llm_facts[-1]["payload"]["content"] == ""


def test_absorb_noop_when_ask_user_failed():
    messages = [
        LLMMessage(
            role="assistant",
            content="正文",
            tool_calls=[_ask_user_call()],
        ),
    ]
    absorbed = absorb_blocking_ask_user_content(
        messages=messages,
        tool_calls=[_ask_user_call()],
        attempts=[ToolAttempt("fp", "ask_user", False)],
        terminal_effect=ToolEffect.SUSPEND,
        emit_reset=lambda _reason: None,
    )
    assert absorbed is False
    assert messages[-1].content == "正文"
