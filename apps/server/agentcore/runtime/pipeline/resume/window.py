"""Rebuild the CEO window from a paused turn's journal projection."""

from __future__ import annotations

from agentcore.core.errors import ResumeJournalDegradedError
from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.engine import join_segments
from agentcore.runtime.journal import window_from_journal
from agentcore.runtime.suspension import TurnSuspension

logger = get_logger(__name__)


def resumed_captain_window(
    suspension: TurnSuspension, history: list[dict] | None
) -> list[LLMMessage]:
    """Rebuild the resumed CEO window from the §8.3 turn journal (Phase 2 ④/⑤).

    The captain transcript at pause is a PROJECTION of the journal, not a stored blob:
    fold ``suspension.journal_entries`` (the fact stream re-hydrated by ``claim_paused_turn``
    from ``turn_journal``, or carried in the Sidecar's local frame) back into the LLM
    window via :func:`window_from_journal`, splicing the reloaded conversation ``history``
    between the captured system prompt and the user message (the journal stores only its
    length — history is itself a projection of earlier turns, supplied by the caller exactly
    as a fresh send builds it: the cloud reloads it from the message DB, the Sidecar from
    its local frame record). The captain run is inferred from the journal's first
    ``role="captain"`` round_boundary, so it does not depend on the frame's ``captain_run_id``.

    ``suspension.transcript`` is NO LONGER serialized (Phase 2 ⑤) — it survives only as an
    in-memory carrier on a same-process resume (tests), so a non-empty one is used (with a
    warning) but a claimed frame's is empty. When BOTH the journal and the in-memory
    transcript are empty the pause is unrecoverable (its best-effort ``turn_journal`` write
    was lost): fail LOUD rather than resume on a silently empty window.
    """
    history_msgs = (
        [LLMMessage(role=h["role"], content=h["content"]) for h in history] if history else None
    )
    window = window_from_journal(suspension.journal_entries, history=history_msgs)
    if window:
        return window
    if suspension.transcript:
        logger.warning(
            "resume.window_from_frame_fallback",
            message_id=suspension.message_id,
            reason="journal_unavailable_inmemory_transcript",
            frame_transcript_len=len(suspension.transcript),
        )
        return list(suspension.transcript)
    if suspension.journal_degraded:
        raise ResumeJournalDegradedError(
            "无法恢复此挂起回合：执行日志保存失败，刷新后上下文已不完整。请停止当前回合并重新发送。",
        )
    if suspension.journal_entries:
        raise RuntimeError(
            "resume: cannot rebuild the CEO window — journal_entries exist "
            f"(count={len(suspension.journal_entries)}) but missing turn_started anchor; "
            f"message_id={suspension.message_id}"
        )
    raise RuntimeError(
        "resume: cannot rebuild the CEO window — no journal_entries to fold and no "
        "in-memory transcript (the pause's turn_journal write was lost); "
        f"message_id={suspension.message_id}"
    )


def pre_pause_content(transcript: list[LLMMessage]) -> str:
    """The CEO's pre-pause reply text for a resumed turn (结构化挂起 2b parity).

    The durable frame's ``transcript`` ends with THIS turn's assistant rounds (the last
    carries the suspended tool_call). A fresh-process resume re-runs the CEO loop from a
    blank ``final_content``, so without this the persisted ``content`` would keep ONLY
    the post-resume text — losing whatever the CEO wrote before it paused (e.g. a
    mid-task overview) and silently shrinking the next turn's LLM history. Rebuild it the
    way the live loop would: join this turn's assistant contents (everything after the
    last user message) as paragraphs. Prior turns (history before that user message) are
    their own messages and are excluded.
    """
    start = 0
    for i in range(len(transcript) - 1, -1, -1):
        if transcript[i].role == "user":
            start = i + 1
            break
    acc = ""
    for msg in transcript[start:]:
        if msg.role == "assistant" and msg.content:
            acc = join_segments(acc, msg.content)
    return acc
