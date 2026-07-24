"""ask_user durable resume — answer→result mapping + frame settlement (结构化挂起 2b).

Pins the pure pieces the ask_user ``POST .../resume`` path adds on top of the
plan_review machinery:

- :func:`ask_user_tool_result` is the SINGLE source of truth shared by the live tool
  and resume — continue feeds the CEO loop a ``CONTINUE`` result, stop returns
  a terminal ``INTERACT`` whose closing note ends the turn in-band, timeout hands
  control back to the CEO. ``ADJUST`` is rejected (plan_review only).
- :func:`_settle_resumed_suspension` applies the user's decision to a paused frame by
  kind: for ask_user it emits the journaled ``checkpoint_resolved``, drops off-menu
  picks (same guard as the live tool), and reports a ``terminal_text`` ONLY for stop
  (so resume finishes without another CEO round).
"""

import pytest

from agentcore.core.types import ToolEffect
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.checkpoints import CheckpointDecision, CheckpointResponse
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.pipeline.resume import (
    finish_terminal_resume,
    pre_pause_content,
    settle_resumed_suspension,
)
from agentcore.runtime.suspension import AskUserSuspension
from agentcore.tools.builtin.ask_user import ask_user_tool_result


def _ask_frame(*, options: list[str] | None = None) -> AskUserSuspension:
    opts = options if options is not None else ["A", "B"]
    return AskUserSuspension(
        message_id="m1",
        conversation_id="c1",
        user_id="u1",
        captain_run_id="cap1",
        checkpoint_id="ck1",
        tool_call_id="call_ask",
        base_system_prompt="base sys",
        user_message="A 还是 B?",
        transcript=[],
        question="A 还是 B?",
        context="",
        questions=[
            {
                "id": "q0",
                "prompt": "A 还是 B?",
                "kind": "choice",
                "options": opts,
                "multiple": False,
                "default": "",
            }
        ],
    )


# --- ask_user_tool_result: the shared answer → ToolResult mapping ------------------


def test_result_continue_folds_picks_and_note():
    res = ask_user_tool_result(
        CheckpointResponse(decision=CheckpointDecision.CONTINUE, note="走稳一点", selected=["A"])
    )
    assert res.effect is ToolEffect.CONTINUE
    assert res.final_text is None  # non-terminal: no in-band closing reply
    assert "A" in res.output and "走稳一点" in res.output


def test_result_stop_is_terminal_with_closing_text():
    res = ask_user_tool_result(
        CheckpointResponse(decision=CheckpointDecision.STOP, note="先到这", selected=[])
    )
    # stop ends the turn in-band: the closing note rides as final_text (the reply),
    # NOT as output (which is the CEO-facing breadcrumb).
    assert res.effect is ToolEffect.INTERACT
    assert res.final_text == "先到这"
    assert "停止" in res.output


def test_result_stop_defaults_closing_when_no_note():
    res = ask_user_tool_result(
        CheckpointResponse(decision=CheckpointDecision.STOP, note="", selected=[])
    )
    assert res.effect is ToolEffect.INTERACT
    assert res.final_text  # a non-empty default closing, so the bubble is never blank


def test_result_adjust_rejected():
    with pytest.raises(ValueError, match="ADJUST"):
        ask_user_tool_result(
            CheckpointResponse(decision=CheckpointDecision.ADJUST, note="走稳一点", selected=["A"])
        )


def test_result_timeout_hands_back_to_ceo():
    res = ask_user_tool_result(CheckpointResponse(decision=CheckpointDecision.TIMEOUT))
    # not terminal — the CEO decides how to wrap up on the next round.
    assert res.effect is ToolEffect.CONTINUE
    assert res.final_text is None


# --- _settle_resumed_suspension: ask_user branch ----------------------------------


def _sink_with_seeded_checkpoint() -> EventSink:
    """An EventSink pre-seeded with the pause's ``checkpoint_required`` — as
    ``resume_chat_pipeline`` does via ``seed_journal`` before settling. Without this
    surface event ``execution_journal`` returns None (nothing to replay)."""
    sink = EventSink()
    sink.seed_journal(
        [{"type": EventType.CHECKPOINT_REQUIRED.value, "payload": {}, "timestamp": "t"}]
    )
    return sink


async def test_settle_ask_user_stop_yields_terminal_text():
    sink = _sink_with_seeded_checkpoint()
    settled = await settle_resumed_suspension(
        _ask_frame(),
        decision=CheckpointDecision.STOP,
        note="收工",
        selected=[],
        sink=sink,
        delegate_tool=None,  # unused on the ask_user branch
        execution_id="",
    )
    # stop → finish WITHOUT another CEO round (the closing note is the whole reply).
    assert settled.terminal_text == "收工"
    assert "停止" in settled.output
    # the resolution is journaled so a reload replays the settled card.
    journal = sink.execution_journal() or []
    assert any(e["type"] == EventType.CHECKPOINT_RESOLVED.value for e in journal)


async def test_settle_ask_user_continue_feeds_loop_without_terminal():
    sink = EventSink()
    settled = await settle_resumed_suspension(
        _ask_frame(),
        decision=CheckpointDecision.CONTINUE,
        note="",
        selected=["A"],
        sink=sink,
        delegate_tool=None,
        execution_id="",
    )
    # continue → no terminal text (run the CEO loop), and the pick rides the result.
    assert settled.terminal_text is None
    assert "A" in settled.output


async def test_settle_ask_user_drops_off_menu_picks():
    # A resolve can't inject arbitrary strings into the CEO context — only offered
    # options survive (same guard as the live AskUserTool).
    sink = _sink_with_seeded_checkpoint()
    settled = await settle_resumed_suspension(
        _ask_frame(options=["A", "B"]),
        decision=CheckpointDecision.CONTINUE,
        note="",
        selected=["A", "HACK"],
        sink=sink,
        delegate_tool=None,
        execution_id="",
    )
    assert "A" in settled.output
    assert "HACK" not in settled.output
    resolved = [
        e
        for e in (sink.execution_journal() or [])
        if e["type"] == EventType.CHECKPOINT_RESOLVED.value
    ]
    assert resolved and resolved[0]["payload"]["selected"] == ["A"]


async def test_settle_organize_plan_continue_keeps_all_selected():
    """B1: organize_plan confirm with full selected (= mobile keep-all) registers all ops."""
    from agentcore.workspace import organize_plan_store

    organize_plan_store.clear_all_for_tests()
    try:
        frame = AskUserSuspension(
            message_id="m1",
            conversation_id="c1",
            user_id="u1",
            captain_run_id="cap1",
            checkpoint_id="ck-org",
            tool_call_id="call_ask",
            base_system_prompt="base",
            user_message="整理桌面",
            transcript=[],
            question="保留哪些操作？",
            context="",
            intent="organize_plan",
            questions=[
                {
                    "id": "q0",
                    "prompt": "保留哪些操作？",
                    "kind": "choice",
                    "multiple": True,
                    "default": "",
                    "options": [
                        {
                            "label": "a → b",
                            "op": "move",
                            "source": "a",
                            "destination": "b",
                        },
                        {"label": "删 x", "op": "delete", "path": "x"},
                    ],
                }
            ],
        )
        sink = _sink_with_seeded_checkpoint()
        settled = await settle_resumed_suspension(
            frame,
            decision=CheckpointDecision.CONTINUE,
            note="",
            selected=["a → b", "删 x"],
            sink=sink,
            delegate_tool=None,
            execution_id="",
        )
        assert settled.terminal_text is None
        assert "plan_id=ck-org" in settled.output
        assert "保留 2 项" in settled.output
        plan = organize_plan_store.get_plan("ck-org")
        assert plan is not None
        assert len(plan.operations) == 2
        resolved = [
            e
            for e in (sink.execution_journal() or [])
            if e["type"] == EventType.CHECKPOINT_RESOLVED.value
        ]
        assert resolved and resolved[0]["payload"]["selected"] == ["a → b", "删 x"]
    finally:
        organize_plan_store.clear_all_for_tests()


# --- pre-pause carry-forward: a 2b resume keeps the CEO's pre-pause reply -----------


def test_pre_pause_content_joins_this_turn_assistant_rounds():
    # The frame transcript ends with this turn's assistant rounds; their joined content
    # (paragraph-separated) is the pre-pause reply — what the live loop already accrued.
    transcript = [
        LLMMessage(role="system", content="sys"),
        LLMMessage(role="user", content="新任务"),
        LLMMessage(role="assistant", content="先看一下需求"),
        LLMMessage(role="assistant", content="我来发问"),
    ]
    assert pre_pause_content(transcript) == "先看一下需求\n\n我来发问"


def test_pre_pause_content_excludes_prior_turns():
    # Only THIS turn counts: assistant text before the last user message belongs to an
    # earlier message and must not leak into the resumed reply.
    transcript = [
        LLMMessage(role="user", content="上一轮"),
        LLMMessage(role="assistant", content="上一轮的回答"),
        LLMMessage(role="user", content="这一轮"),
        LLMMessage(role="assistant", content="这一轮开场"),
    ]
    assert pre_pause_content(transcript) == "这一轮开场"


def test_pre_pause_content_empty_when_no_preamble():
    # The ideal ask_user shape (after the prompt fix): the CEO calls ask_user with an
    # empty body, so there is nothing to carry forward.
    transcript = [
        LLMMessage(role="user", content="问"),
        LLMMessage(role="assistant", content=""),
    ]
    assert pre_pause_content(transcript) == ""


def test_finish_terminal_resume_prepends_pre_pause_to_closing():
    # ask_user STOP after the CEO already wrote an overview: the persisted reply is the
    # overview + closing note as separate paragraphs (parity with live), not the closing
    # note alone — the pre-pause text must not be dropped on a fresh-process resume.
    result = finish_terminal_resume(
        message_id="m1",
        pre_pause_content="阶段成果如上。",
        closing="先到这。",
        sink=EventSink(),
    )
    assert result["content"] == "阶段成果如上。\n\n先到这。"


def test_finish_terminal_resume_keeps_closing_only_without_pre_pause():
    result = finish_terminal_resume(
        message_id="m1", pre_pause_content="", closing="先到这。", sink=EventSink()
    )
    assert result["content"] == "先到这。"
