"""Bill and close a resumed turn after settlement."""

from __future__ import annotations

from dataclasses import asdict

from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.runtime.citations import merge_citations, reconcile_citations
from agentcore.runtime.closing_posture import reconcile_resume_closing
from agentcore.runtime.costing import aggregate_cost, captain_run_cost_from_state
from agentcore.runtime.engine import join_segments
from agentcore.runtime.events import EventSink, FinishReason, citations_event, message_end
from agentcore.runtime.facts import current_fact_log
from agentcore.runtime.ledger_channel import emit_turn_evidence_ledger
from agentcore.runtime.pipeline.finalize import _journal_entries_for_turn
from agentcore.tools.builtin.debate import DebateTool
from agentcore.tools.builtin.delegate import DelegateTool

logger = get_logger(__name__)


async def finish_resume_turn(
    *,
    message_id: str,
    captain_run_id: str,
    captain_state,
    pre_pause_content: str,
    delegate_tool: DelegateTool,
    debate_tool: DebateTool,
    profile,
    citations: list[dict],
    sink: EventSink,
    vision_cost_runs: list | None = None,
    audit_drops: int = 0,
    pre_pause_reasoning: str = "",
) -> dict:
    """Bill + close a resumed turn whose CEO loop ran (plan_review / ask_user continue).

    The whole turn bills once here: the captain's resume round + any delegated
    workers' usage (seeds + tail, folded by ``resume_plan``) + any continuation.
    Mirrors :func:`run_chat_pipeline`'s tail (usage roll-up, per-run ledger, citations,
    message_end), returning the same result shape for the service to persist.

    ``vision_cost_runs`` are the resumed turn's board_read 读图 ledger rows (role=vision,
    §九.4 Gap ②), collected off the shared ``ToolContext.cost_sink``. Folded into
    ``cost_runs`` like the delegate rows; vision spend has no usage that rolls
    into ``turn_usage`` (a separate model, billed only as its own priced row).

    ``pre_pause_reasoning`` joins ahead of the live captain reasoning (G3) so
    multi-cycle pauses keep ``join(join(r1, r2), live)`` continuity.
    """
    # 受监督的波循环 P5「Edge」(parity with settle_successful_turn): the resume-segment
    # drive may have yielded at a BIND/SCOPE boundary (or stashed a partial failure) and
    # the CEO answered WITHOUT a replan — those completed workers' usage / ledger /
    # citations were deliberately NOT folded on the yield path. Dispose (implicit stop)
    # BEFORE the usage / cost / citations fold below, else that spend is stranded
    # unbilled. No-op when nothing is paused.
    await delegate_tool.dispose_open_supervised()

    # 完成态互斥：禁「请确认」pre_pause ∪「已全部收卷」续写硬拼（cef27dfa / e8fb470c）。
    final_content = reconcile_resume_closing(pre_pause_content, captain_state.content)
    final_reasoning = join_segments(pre_pause_reasoning, captain_state.reasoning or "") or None
    rounds = captain_state.rounds
    turn_usage = (
        TokenUsage.from_usage_dict(captain_state.usage)
        + TokenUsage.from_usage_dict(delegate_tool.usage)
        + TokenUsage.from_usage_dict(debate_tool.usage)
    )
    finish = captain_state.finish_override or (
        FinishReason.END_TURN if rounds < profile.max_rounds else FinishReason.MAX_ROUNDS
    )
    captain_cost = captain_run_cost_from_state(captain_run_id, captain_state)
    cost_runs = [
        asdict(captain_cost),
        *(asdict(r) for r in delegate_tool.run_ledger),
        *(asdict(r) for r in debate_tool.run_ledger),
        # board_read 视觉子调用账（§九.4 Gap ②），与 delegate 同形折账。
        *(asdict(r) for r in (vision_cost_runs or [])),
    ]
    turn_cost = aggregate_cost(cost_runs)
    merge_citations(citations, delegate_tool.citations)
    merge_citations(citations, debate_tool.citations)
    # Mirror run_chat_pipeline: observe then strip dangling [n] / #rN before persist.
    led = None
    citable_ids = None
    try:
        from agentcore.runtime.suspension import turn_evidence_ledger

        led = turn_evidence_ledger.get()
        if led is not None:
            led.mark_selected_from_content(final_content)
            citable_ids = led.draft_citable_ids()
    except Exception:
        logger.warning("citations.ledger_lookup_failed", message_id=message_id, exc_info=True)
    final_content, citations, stray_n, stray_r = reconcile_citations(
        final_content, citations, citable_ids=citable_ids
    )
    if stray_n:
        logger.warning(
            "citations.out_of_range",
            message_id=message_id,
            markers=stray_n,
            citation_count=len(citations),
        )
    if stray_r:
        logger.warning(
            "citations.invalid_ledger_ref",
            message_id=message_id,
            markers=stray_r,
            citable_count=len(citable_ids or ()),
        )
    citations, evidence_ledger, cited_ids = emit_turn_evidence_ledger(
        sink, ledger=led, content=final_content, citations=citations
    )
    if citations:
        sink.emit(citations_event(citations))
    collab = {
        **delegate_tool.collab,
        "revises": delegate_tool.continuation_count,
        "audit_drops": audit_drops,
    }
    sink.emit(
        message_end(
            finish,
            input_tokens=turn_usage.input_tokens,
            output_tokens=turn_usage.output_tokens,
            reasoning_tokens=turn_usage.reasoning_tokens,
            cache_hit_tokens=turn_usage.cache_hit_tokens,
            cache_miss_tokens=turn_usage.cache_miss_tokens,
            rounds=rounds,
            cost=turn_cost,
            collab=collab,
        )
    )
    journal_entries = _journal_entries_for_turn(current_fact_log.get(), sink=sink, finish=finish)
    return {
        "message_id": message_id,
        "content": final_content,
        "reasoning_content": final_reasoning,
        "input_tokens": turn_usage.input_tokens,
        "output_tokens": turn_usage.output_tokens,
        "reasoning_tokens": turn_usage.reasoning_tokens,
        "cache_hit_tokens": turn_usage.cache_hit_tokens,
        "cache_miss_tokens": turn_usage.cache_miss_tokens,
        "rounds": rounds,
        "finish_reason": finish,
        "citations": citations,
        "evidence_ledger": evidence_ledger,
        "cited_ids": cited_ids,
        "cost_runs": cost_runs,
        "journal_entries": journal_entries,
        # 协作质量 (学·度量 §2.5): same turn-level signals as the fresh-turn path.
        "collab": collab,
    }


def finish_terminal_resume(
    *,
    message_id: str,
    pre_pause_content: str,
    closing: str,
    sink: EventSink,
    pre_pause_reasoning: str = "",
) -> dict:
    """Close a resumed ask_user turn that the user STOPPED (结构化挂起 2b terminal).

    No CEO round ran — the closing note is the whole reply (the engine's
    terminal-effect semantics, replayed on resume). The pre-pause CEO round that
    raised the ask_user was never billed (the turn paused before persistence), and a
    stop runs nothing new, so this turn bills nothing — consistent with the「paused
    before persist = never billed」model. The seeded journal (checkpoint_required) +
    the emitted ``checkpoint_resolved`` persist so a reload replays the settled card.

    ``pre_pause_reasoning`` is preserved as the turn's reasoning (no live segment to
    join — G3 terminal path).
    """
    finish = FinishReason.END_TURN
    sink.emit(message_end(finish, rounds=0))
    journal_entries = _journal_entries_for_turn(current_fact_log.get(), sink=sink, finish=finish)
    return {
        "message_id": message_id,
        "content": reconcile_resume_closing(pre_pause_content, closing),
        "reasoning_content": pre_pause_reasoning or None,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_hit_tokens": 0,
        "cache_miss_tokens": 0,
        "rounds": 0,
        "finish_reason": finish,
        "citations": [],
        "cost_runs": [],
        "journal_entries": journal_entries,
    }
