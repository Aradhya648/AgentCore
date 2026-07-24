"""Bug ratchet: same-turn double suspend must persist settled tool results.

Root cause: pause skips ToolCallFact (no phantom); first resume only patched the
in-memory transcript; second pause folded an assistant with tool_calls and no
matching tool messages → upstream 400.

Fix: ``persist_resumed_tool_results`` after settle so ``window_from_journal`` closes
the pair for any later same-turn re-pause.
"""

from __future__ import annotations

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.events import EventSink
from agentcore.runtime.facts import (
    FactKind,
    LlmCallFact,
    RoundBoundaryFact,
    ToolCallFact,
    TurnFactLog,
    TurnStartedFact,
    current_fact_log,
)
from agentcore.runtime.journal import window_from_journal
from agentcore.runtime.pipeline.resume.settle import (
    append_resumed_tool_results,
    persist_resumed_tool_results,
)


def _unclosed_tool_call_ids(messages: list[LLMMessage]) -> set[str]:
    pending: set[str] = set()
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                pending.add(tc.id)
        elif m.role == "tool" and m.tool_call_id:
            pending.discard(m.tool_call_id)
    return pending


def _delegate_then_ask_journal(*, with_delegate_fact: bool) -> list[dict]:
    """Captain: delegate (settled or not) → ask_user (still suspended)."""
    entries = [
        TurnStartedFact(system_prompt="你是 CEO。", user_message="组团队调研", model_profile="m")
        .to_fact()
        .entry(),
        RoundBoundaryFact(round_idx=0, run_id="cap", role="captain").to_fact().entry(),
        LlmCallFact(
            run_id="cap",
            round_idx=0,
            tool_calls=[
                {
                    "id": "call_del",
                    "type": "function",
                    "function": {
                        "name": "delegate",
                        "arguments": '{"tasks":[{"role":"研究员","task":"查"}]}',
                    },
                }
            ],
            finish_reason="tool_calls",
        )
        .to_fact()
        .entry(),
    ]
    if with_delegate_fact:
        entries.append(
            ToolCallFact(
                run_id="cap",
                tool_call_id="call_del",
                name="delegate",
                arguments='{"tasks":[{"role":"研究员","task":"查"}]}',
                result="团队已启动，2 名队员进行中。",
                success=True,
            )
            .to_fact()
            .entry()
        )
        entries.append(
            RoundBoundaryFact(round_idx=1, run_id="cap", role="captain").to_fact().entry()
        )
        entries.append(
            LlmCallFact(
                run_id="cap",
                round_idx=1,
                tool_calls=[
                    {
                        "id": "call_ask",
                        "type": "function",
                        "function": {
                            "name": "ask_user",
                            "arguments": '{"question":"选哪个方案？"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
            .to_fact()
            .entry()
        )
    return entries


def test_double_suspend_fold_closes_after_persist_resumed_tool_results():
    """delegate→ask_user same-turn: after both settles, fold has no open tool_calls."""
    # --- First pause (delegate): journal has no ToolCallFact ---
    pause1 = _delegate_then_ask_journal(with_delegate_fact=False)
    folded1 = window_from_journal(pause1)
    assert folded1 is not None
    assert _unclosed_tool_call_ids(folded1) == {"call_del"}

    # First resume settle: memory splice + persist into ambient fact log.
    fact_log = TurnFactLog(inherited_entries=list(pause1))
    token = current_fact_log.set(fact_log)
    sink = EventSink()
    try:
        messages = list(folded1)
        settled_delegate = "团队已启动，2 名队员进行中。"
        append_resumed_tool_results(messages, "call_del", settled_delegate)
        persist_resumed_tool_results(
            folded1,
            tool_call_id="call_del",
            output=settled_delegate,
            run_id="cap",
            sink=sink,
            tool_name="delegate",
        )
        after_first_settle = fact_log.entries()
    finally:
        current_fact_log.reset(token)

    assert any(
        (e.get("kind") or "") == FactKind.TOOL_CALL.value
        and (e.get("payload") or {}).get("tool_call_id") == "call_del"
        for e in after_first_settle
    )
    assert any(
        (e.get("kind") or "") == "tool_use_end"
        and (e.get("payload") or {}).get("tool_call_id") == "call_del"
        for e in after_first_settle
    )
    folded_after_delegate = window_from_journal(after_first_settle)
    assert folded_after_delegate is not None
    assert _unclosed_tool_call_ids(folded_after_delegate) == set()

    # --- Second pause (ask_user): without first persist, both calls stay open ---
    pause2_missing_delegate_fact = list(pause1)
    pause2_missing_delegate_fact.extend(
        [
            RoundBoundaryFact(round_idx=1, run_id="cap", role="captain").to_fact().entry(),
            LlmCallFact(
                run_id="cap",
                round_idx=1,
                tool_calls=[
                    {
                        "id": "call_ask",
                        "type": "function",
                        "function": {
                            "name": "ask_user",
                            "arguments": '{"question":"选哪个方案？"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )
            .to_fact()
            .entry(),
        ]
    )
    broken_fold = window_from_journal(pause2_missing_delegate_fact)
    assert broken_fold is not None
    assert "call_del" in _unclosed_tool_call_ids(broken_fold)

    # With persist, second pause only leaves ask_user open.
    pause2 = _delegate_then_ask_journal(with_delegate_fact=True)
    folded2 = window_from_journal(pause2)
    assert folded2 is not None
    assert _unclosed_tool_call_ids(folded2) == {"call_ask"}

    # Second resume settle persists ask_user.
    fact_log2 = TurnFactLog(inherited_entries=list(pause2))
    token2 = current_fact_log.set(fact_log2)
    sink2 = EventSink()
    try:
        settled_ask = "用户选择了方案 A。"
        append_resumed_tool_results(list(folded2), "call_ask", settled_ask)
        persist_resumed_tool_results(
            folded2,
            tool_call_id="call_ask",
            output=settled_ask,
            run_id="cap",
            sink=sink2,
            tool_name="ask_user",
        )
        after_second = fact_log2.entries()
    finally:
        current_fact_log.reset(token2)

    folded_final = window_from_journal(after_second)
    assert folded_final is not None
    assert _unclosed_tool_call_ids(folded_final) == set()
    roles = [m.role for m in folded_final]
    assert roles.count("assistant") == 2
    assert roles.count("tool") == 2
    tool_ids = [m.tool_call_id for m in folded_final if m.role == "tool"]
    assert tool_ids == ["call_del", "call_ask"]
