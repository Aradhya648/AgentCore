"""One-off dev cleanup: drop 团队便签 (team_note_posted) facts left on DEBATE turns.

Before the 辩论去团队便签 fix (`build_agent_executor` 的 ``collaboration`` 开关 —— 辩手是对手
不是协作团队，不再配便签墙), a debate ran through the executor's unconditional 便签墙
provisioning, so debaters could ``post_note`` and every post emitted a JOURNALED
``team_note_posted`` fact. Those facts persist in the ``turn_journal`` (§8.3 唯一事实源) and
still fold onto the assistant message's replay, so a PRE-FIX debate turn keeps rendering a
spurious「团队便签」panel on reload.

The code fix is forward-only (new debates provision NO wall, emit NO note). This prunes the
STALE facts from已存在的 debate turns so历史 debates 也回溯变干净. It is a **dev convenience**
(开发期无真实数据, 产品负责人 confirmed 存量按需清理 → no production migration); it only touches
the database — nothing on disk.

Scope = a ``team_note_posted`` row whose OWNING TURN also carries a ``debate_result`` row (i.e.
the turn ran a debate). ``debate_round`` / ``debate_round_started`` are transport-only (never
journaled), so ``debate_result`` is the durable marker of a debate turn. Delegate-collaboration
turns (no ``debate_result``) are LEFT ALONE —— their便签 are legitimate team broadcasts.

The fold-cache key includes the journal entry count (``runtime/journal/fold_cache.py``), so a
pruned turn re-projects fresh on the next read: just reload the conversation, no server restart
needed.

CAVEAT: a single turn that BOTH delegated (legit notes) AND debated (leaked notes) would have
all its team notes pruned (turn-level scope). That mix is not expected in dev data; the dry-run
prints每 note's kind + author + text so you can eyeball before ``--apply``.

Run from ``apps/server``::

    # preview only (default): list what WOULD be pruned, change nothing
    uv run python scripts/cleanup_debate_team_notes.py

    # actually prune (hard-delete the rows) across all conversations
    uv run python scripts/cleanup_debate_team_notes.py --apply

    # scope the preview / prune to a single conversation
    uv run python scripts/cleanup_debate_team_notes.py --conversation <conversation_id> --apply
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, select

from agentcore.db import async_session_factory
from agentcore.db.models import TurnJournalRow
from agentcore.runtime.events.types import EventType

_NOTE_KIND = EventType.TEAM_NOTE_POSTED.value  # "team_note_posted"
_DEBATE_KIND = EventType.DEBATE_RESULT.value  # "debate_result"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Prune stale 团队便签 (team_note_posted) facts from debate turns (dev cleanup).",
    )
    p.add_argument(
        "--conversation",
        default=None,
        help="scope to a single conversation_id (default: all conversations)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="perform the deletion (default: dry-run preview only)",
    )
    return p.parse_args()


async def _run(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        # Debate turns = turns carrying a debate_result fact (the durable marker; the
        # per-round events are transport-only and never reach the journal).
        debate_turns_q = select(TurnJournalRow.turn_id).where(TurnJournalRow.kind == _DEBATE_KIND)
        if args.conversation:
            debate_turns_q = debate_turns_q.where(
                TurnJournalRow.conversation_id == args.conversation
            )
        debate_turns = set((await session.execute(debate_turns_q)).scalars().all())

        if not debate_turns:
            print("no debate turns found — nothing to do.")
            return

        # The stale note facts to prune: team_note_posted rows on those debate turns.
        # Materialize the set so preview and apply target the EXACT same rows (a
        # concurrent new note between the two phases is not silently swept).
        notes = (
            (
                await session.execute(
                    select(TurnJournalRow)
                    .where(
                        TurnJournalRow.kind == _NOTE_KIND,
                        TurnJournalRow.turn_id.in_(debate_turns),
                    )
                    .order_by(TurnJournalRow.turn_id, TurnJournalRow.seq)
                )
            )
            .scalars()
            .all()
        )

        if not notes:
            print(
                f"found {len(debate_turns)} debate turn(s), but none carry team_note_posted "
                "facts — already clean, nothing to do."
            )
            return

        by_turn: dict[str, list[TurnJournalRow]] = {}
        for row in notes:
            by_turn.setdefault(row.turn_id, []).append(row)

        verb = "Pruning" if args.apply else "Would prune"
        print(f"{verb} {len(notes)} team-note fact(s) across {len(by_turn)} debate turn(s):\n")
        for turn_id, rows in by_turn.items():
            print(f"  • turn={turn_id}  conversation={rows[0].conversation_id}  notes={len(rows)}")
            for r in rows:
                payload = r.payload or {}
                author = payload.get("role") or payload.get("agent_id") or "?"
                note_kind = payload.get("kind") or "?"
                text = (payload.get("text") or "").replace("\n", " ")
                if len(text) > 80:
                    text = text[:77] + "..."
                print(f"      [{note_kind}] {author}: {text}")

        if not args.apply:
            print("\n[dry-run] no changes made. Re-run with --apply to prune.")
            return

        result = await session.execute(
            delete(TurnJournalRow).where(
                TurnJournalRow.kind == _NOTE_KIND,
                TurnJournalRow.turn_id.in_(debate_turns),
            )
        )
        await session.commit()
        print(
            f"\ndone: pruned {result.rowcount} team-note fact(s) from {len(by_turn)} debate "
            "turn(s). Reload the conversation to see the「团队便签」panel gone "
            "(fold cache re-projects on read — no server restart needed)."
        )


if __name__ == "__main__":
    asyncio.run(_run(_parse_args()))
