"""Resume recover path: settle checkpoint, rebuild window, optional continuity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.events import EventSink
from agentcore.runtime.pipeline.resume.settle import (
    append_resumed_tool_results,
    persist_resumed_tool_results,
)
from agentcore.runtime.pipeline.resume.window import pre_pause_content, resumed_captain_window
from agentcore.runtime.recover import recover_turn
from agentcore.runtime.suspension import TurnSuspension, captain_transcript
from agentcore.runtime.turn_state import TurnState

logger = get_logger(__name__)


@dataclass
class RecoveredResume:
    """Post-recover window ready for terminal finish or captain continuation."""

    messages: list[LLMMessage]
    pre_pause: str
    settled: Any


async def recover_and_rebuild_window(
    *,
    suspension: TurnSuspension,
    decision: CheckpointDecision,
    note: str,
    selected: list[str] | None,
    history: list[dict] | None,
    sink: EventSink,
    delegate_tool: Any,
    debate_tool: Any,
    execution_id: str,
    captain_run_id: str,
    pre_pause_override: str | None = None,
    style_id: str | None = None,
    format_id: str | None = None,
) -> RecoveredResume:
    """Settle the paused frame and rebuild the CEO message window.

    ``pre_pause_override`` (from ``turn_paused.content``) replaces the transcript
    heuristic when the resume path rehydrated a pause snapshot; ``None`` keeps the
    legacy ``pre_pause_content(transcript)`` path for old frames.
    """
    # Rebuild the CEO window by FOLDING the turn journal (Phase 2 ④): the captain
    # transcript at pause is a projection of the §8.3 facts, not a stored blob —
    # window_from_journal(journal_entries) + the reloaded history reconstructs the
    # exact messages the CEO suspended on (the conformance golden gates this ==).
    transcript = resumed_captain_window(suspension, history)

    # Publish the pre-pause CEO transcript so a re-pause DURING the settle (a
    # second downstream checkpoint while resume_plan runs) captures the same
    # transcript the CEO is still suspended on — symmetric with the original pause.
    token = captain_transcript.set(transcript)
    try:
        # Single recover primitive: journal projection → seed WaveScheduler / settle.
        turn_state = TurnState.from_journal(
            suspension.journal_entries,
            display_journal=suspension.journal,
        )
        settled = await recover_turn(
            state=turn_state,
            sink=sink,
            delegate_tool=delegate_tool,
            debate_tool=debate_tool,
            execution_id=execution_id,
            suspension=suspension,
            decision=decision,
            note=note,
            selected=selected or [],
            style_id=style_id,
            format_id=format_id,
        )
        logger.info(
            "pipeline.resume_settled",
            checkpoint_id=suspension.checkpoint_id,
            decision=decision.value,
            kind=suspension.kind.value,
        )
    finally:
        captain_transcript.reset(token)

    # Rebuild the CEO transcript: the folded window (ending at the assistant
    # suspended call) + that call's settled tool result.
    messages = list(transcript)
    # Carry the CEO's pre-pause reply forward: the resumed loop below starts from a
    # blank content, so without this the persisted content (and the next turn's LLM
    # history) would lose everything written before the pause — parity with live.
    # ``turn_paused.content`` is authoritative when present (G4); else transcript heuristic.
    pre_pause = (
        pre_pause_override if pre_pause_override is not None else pre_pause_content(transcript)
    )
    append_resumed_tool_results(messages, suspension.tool_call_id, settled.output)
    # Pause skipped ToolCallFact (no phantom). Settlement produced a real result —
    # persist it (+ display tool_use_end) so a same-turn re-pause folds a closed pair.
    persist_resumed_tool_results(
        transcript,
        tool_call_id=suspension.tool_call_id,
        output=settled.output,
        run_id=captain_run_id,
        sink=sink,
        tool_name=getattr(suspension.kind, "value", "") or "",
    )

    # 终稿多段衔接: when the pause kept deliverable prose, steer the resumed answer
    # round to continue it (join_segments alone can't invent transitions). Skip when
    # the user STOPPED (terminal_text path finishes without another CEO round).
    if pre_pause.strip() and settled.terminal_text is None:
        from agentcore.runtime.engine import deliverable_continuity_instruction
        from agentcore.runtime.facts import NoteFact, record_turn_fact

        continuity = deliverable_continuity_instruction(prior_deliverable=pre_pause)
        messages.append(LLMMessage(role="user", content=continuity))
        record_turn_fact(
            NoteFact(
                role="user",
                content=continuity,
                reason="continuity",
                run_id=captain_run_id,
            ).to_fact()
        )

    return RecoveredResume(messages=messages, pre_pause=pre_pause, settled=settled)
