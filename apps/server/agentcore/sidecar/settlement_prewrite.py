"""Sidecar local settlement prewrite (回合恢复状态机收口 · D1).

Mirrors cloud ``prewrite_cold_resume_settlement`` against the local OutboxStore:
durable ``*_resolved`` lands in the outbox journal **before** the paused frame is
consumed. The settlement payload may embed ``resume_frame`` as audit/control
metadata (frameless continue-after-decision was abolished).
"""

from __future__ import annotations

from typing import Any

from agentcore.conversation.store.outbox import OutboxStore, journal_entries_from_map
from agentcore.runtime.settlement import cold_resume_settlement_event, entry_from_sse
from agentcore.runtime.suspension import TurnSuspension


def resume_frame_blob(
    suspension: TurnSuspension,
    *,
    user_message_id: str,
    decision: str,
    note: str,
    selected: list[str],
) -> dict[str, Any]:
    """Settlement control metadata embedded alongside ``*_resolved``."""
    return {
        "frame": suspension.to_json(),
        "history": list(suspension.history),
        "journal_entries": list(suspension.journal_entries),
        "user_message_id": user_message_id,
        "decision": decision,
        "note": note,
        "selected": list(selected),
    }


async def prewrite_sidecar_resume_settlement(
    outbox: OutboxStore,
    suspension: TurnSuspension,
    *,
    decision: str,
    note: str = "",
    selected: list[str] | None = None,
    user_message_id: str,
    trace_id: str = "",
) -> dict[str, Any]:
    """Durable-write ``*_resolved`` (+ resume_frame) into the outbox journal.

    Raises on write failure so the caller can restore the claimed frame.
    Returns the journal entry that was written (also appended onto
    ``suspension.journal_entries`` for resume-pipeline dedupe seeding).
    """
    picks = list(selected or [])
    event = cold_resume_settlement_event(
        suspension, decision=decision, note=note, selected=picks
    )
    entry = entry_from_sse(event)
    entry["payload"] = {
        **dict(entry.get("payload") or {}),
        "resume_frame": resume_frame_blob(
            suspension,
            user_message_id=user_message_id,
            decision=decision,
            note=note,
            selected=picks,
        ),
    }
    await outbox.append_journal_durable(
        turn_id=suspension.message_id,
        conversation_id=suspension.conversation_id,
        trace_id=trace_id or getattr(suspension, "trace_id", None),
        entry=entry,
        user_message_id=user_message_id,
    )
    suspension.journal_entries = list(suspension.journal_entries) + [entry]
    return entry


def settlement_keys_in_entries(
    entries: list[dict[str, Any]] | None,
) -> set[tuple[str, str]]:
    """Return ``{(resolved_kind, checkpoint_id)}`` present in journal entries."""
    found: set[tuple[str, str]] = set()
    for entry in entries or []:
        kind = str(entry.get("kind") or entry.get("type") or "")
        if not kind.endswith("_resolved"):
            continue
        payload = dict(entry.get("payload") or {})
        cid = str(payload.get("checkpoint_id") or "")
        if cid:
            found.add((kind, cid))
    return found


def outbox_has_settlement_for_frame(
    outbox_base: Any,
    *,
    message_id: str,
    checkpoint_id: str,
    suspension_kind: str,
) -> bool:
    """True when an outbox journal already holds the matching ``*_resolved``."""
    from pathlib import Path

    from agentcore.conversation.store.outbox import list_outbox_records

    kind_to_resolved = {
        "ask_user": "checkpoint_resolved",
        "plan_review": "plan_review_resolved",
        "team_preview": "team_preview_resolved",
    }
    resolved_kind = kind_to_resolved.get(suspension_kind)
    if not resolved_kind or not checkpoint_id:
        return False
    base = Path(outbox_base)
    for record in list_outbox_records(base):
        if str(record.get("message_id") or "") != message_id:
            continue
        entries = journal_entries_from_map(record.get("journal")) or []
        if (resolved_kind, checkpoint_id) in settlement_keys_in_entries(entries):
            return True
    return False
