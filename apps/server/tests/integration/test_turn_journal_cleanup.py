"""Integration: turn_journal is cleaned with its owning message / conversation.

Backed by real PostgreSQL via ``session_factory`` (auto-skips when none reachable).
Pins the app-level cascade (no DB FK) that keeps the §18.3 唯一事实源 from orphaning:
a conversation hard-delete, a regenerate/edit truncate (``delete_after``), and a
single-message delete each drop the matching turn_journal rows — while a
cross-conversation id (IDOR) touches neither the message nor its journal.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import update

from agentcore.db.models import Message
from agentcore.db.repositories import (
    ConversationRepository,
    MessageRepository,
    PausedTurnRepository,
    TurnJournalRepository,
)

_ENTRIES = [{"kind": "run_plan", "payload": {}, "ts": "t"}]


async def _seed_turn(s, *, cid: str, mid: str) -> None:
    """One assistant message + its journal row (same id), as a completed turn writes."""
    await MessageRepository(s).create(
        conversation_id=cid, role="assistant", content="x", message_id=mid
    )
    await TurnJournalRepository(s).record(
        turn_id=mid, conversation_id=cid, trace_id=None, entries=_ENTRIES
    )


async def test_conversation_hard_delete_clears_turn_journal(session_factory):
    cid = str(uuid4())
    m1, m2 = str(uuid4()), str(uuid4())
    async with session_factory() as s:
        await _seed_turn(s, cid=cid, mid=m1)
        await _seed_turn(s, cid=cid, mid=m2)

    async with session_factory() as s:
        await ConversationRepository(s).hard_delete(cid)

    async with session_factory() as s:
        repo = TurnJournalRepository(s)
        assert await repo.load(m1) == []
        assert await repo.load(m2) == []


async def test_delete_after_clears_only_truncated_turns_journal(session_factory):
    # regenerate / edit-and-resend truncates the tail; only the dropped turns' journal
    # goes — the kept turn's replay stream stays.
    cid = str(uuid4())
    keep, drop = str(uuid4()), str(uuid4())
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    async with session_factory() as s:
        await _seed_turn(s, cid=cid, mid=keep)
        await _seed_turn(s, cid=cid, mid=drop)
        # Pin created_at: keep at t0, drop one minute later (strictly after t0).
        await s.execute(update(Message).where(Message.id == keep).values(created_at=t0))
        await s.execute(
            update(Message).where(Message.id == drop).values(created_at=t0 + timedelta(minutes=1))
        )
        await s.commit()

    async with session_factory() as s:
        removed = await MessageRepository(s).delete_after(cid, after_created_at=t0)
    assert removed == 1  # only `drop`

    async with session_factory() as s:
        repo = TurnJournalRepository(s)
        assert await repo.load(keep) == _ENTRIES  # kept turn's journal survives
        assert await repo.load(drop) == []  # truncated turn's journal gone


async def _seed_paused(s, *, cid: str, mid: str, uid: str | None = None) -> None:
    await PausedTurnRepository(s).upsert(
        message_id=mid,
        conversation_id=cid,
        user_id=uid or str(uuid4()),
        frame={"kind": "plan_review", "message_id": mid},
    )


async def test_delete_by_id_clears_paused_turn(session_factory):
    cid, mid = str(uuid4()), str(uuid4())
    async with session_factory() as s:
        await _seed_turn(s, cid=cid, mid=mid)
        await _seed_paused(s, cid=cid, mid=mid)

    async with session_factory() as s:
        hit = await MessageRepository(s).delete_by_id(mid, conversation_id=cid)
    assert hit is True

    async with session_factory() as s:
        assert await PausedTurnRepository(s).get(mid) is None


async def test_delete_after_clears_only_truncated_paused_turns(session_factory):
    cid = str(uuid4())
    keep, drop = str(uuid4()), str(uuid4())
    uid = str(uuid4())
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    async with session_factory() as s:
        await _seed_turn(s, cid=cid, mid=keep)
        await _seed_turn(s, cid=cid, mid=drop)
        await _seed_paused(s, cid=cid, mid=keep, uid=uid)
        await _seed_paused(s, cid=cid, mid=drop, uid=uid)
        await s.execute(update(Message).where(Message.id == keep).values(created_at=t0))
        await s.execute(
            update(Message).where(Message.id == drop).values(created_at=t0 + timedelta(minutes=1))
        )
        await s.commit()

    async with session_factory() as s:
        removed = await MessageRepository(s).delete_after(cid, after_created_at=t0)
    assert removed == 1

    async with session_factory() as s:
        repo = PausedTurnRepository(s)
        assert await repo.get(keep) is not None
        assert await repo.get(drop) is None


async def test_delete_by_id_clears_journal_and_is_idor_safe(session_factory):
    cid, other_cid = str(uuid4()), str(uuid4())
    mid = str(uuid4())
    async with session_factory() as s:
        await _seed_turn(s, cid=cid, mid=mid)

    # Wrong conversation → neither the message nor its journal is touched (IDOR-safe).
    async with session_factory() as s:
        hit = await MessageRepository(s).delete_by_id(mid, conversation_id=other_cid)
    assert hit is False
    async with session_factory() as s:
        assert await TurnJournalRepository(s).load(mid) == _ENTRIES

    # Right conversation → message + journal both removed.
    async with session_factory() as s:
        hit = await MessageRepository(s).delete_by_id(mid, conversation_id=cid)
    assert hit is True
    async with session_factory() as s:
        assert await TurnJournalRepository(s).load(mid) == []
