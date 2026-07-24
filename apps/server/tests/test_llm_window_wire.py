"""Unit tests for diagnostic LLM window wire projection."""

from agentcore.runtime.facts import (
    LlmCallFact,
    RoundBoundaryFact,
    RunHeadFact,
    ToolCallFact,
    TurnStartedFact,
)
from agentcore.runtime.journal.window_wire import project_run_llm_window


def test_project_run_llm_window_folds_captain_tool_round():
    run_id = "cap"
    entries = [
        TurnStartedFact(
            system_prompt="SYS",
            user_message="go",
            model_profile="chat",
            history_len=0,
        )
        .to_fact()
        .entry(),
        RoundBoundaryFact(round_idx=0, run_id=run_id, role="captain").to_fact().entry(),
        LlmCallFact(
            run_id=run_id,
            round_idx=0,
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
            finish_reason="tool_calls",
        )
        .to_fact()
        .entry(),
        ToolCallFact(
            run_id=run_id,
            tool_call_id="c1",
            name="search",
            arguments="{}",
            result="hit",
            success=True,
        )
        .to_fact()
        .entry(),
    ]
    resp = project_run_llm_window(entries, run_id=run_id)
    assert resp.available is True
    assert [m.role for m in resp.messages] == ["system", "user", "assistant", "tool"]
    assert resp.messages[2].tool_calls[0].function.name == "search"
    assert resp.messages[3].content == "hit"
    # Captain opening user has no context_blocks origin.
    assert resp.messages[1].origin is None


def test_project_run_llm_window_worker_run_head_origin():
    entries = [
        TurnStartedFact(
            system_prompt="CEO-SYS",
            user_message="build",
            model_profile="chat",
        )
        .to_fact()
        .entry(),
        RoundBoundaryFact(round_idx=0, run_id="cap", role="captain").to_fact().entry(),
        RunHeadFact(
            run_id="w1",
            system_prompt="WORKER-SYS",
            user_message="## 你的任务\n调研",
            user_origin="context_blocks",
        )
        .to_fact()
        .entry(),
        RoundBoundaryFact(round_idx=0, run_id="w1", role="worker").to_fact().entry(),
        LlmCallFact(
            run_id="w1",
            round_idx=0,
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                }
            ],
            finish_reason="tool_calls",
        )
        .to_fact()
        .entry(),
        ToolCallFact(
            run_id="w1",
            tool_call_id="c1",
            name="web_search",
            arguments="{}",
            result="ok",
            success=True,
        )
        .to_fact()
        .entry(),
    ]
    resp = project_run_llm_window(entries, run_id="w1")
    assert resp.available is True
    assert resp.messages[0].content == "WORKER-SYS"
    assert resp.messages[0].origin is None
    assert resp.messages[1].role == "user"
    assert resp.messages[1].content == "## 你的任务\n调研"
    assert resp.messages[1].origin == "context_blocks"
    assert resp.messages[2].role == "assistant"


def test_project_run_llm_window_unavailable_without_turn_started():
    resp = project_run_llm_window(
        [{"kind": "turn_end", "payload": {"finish_reason": "end_turn"}}],
        run_id="cap",
    )
    assert resp.available is False
    assert resp.messages == []
