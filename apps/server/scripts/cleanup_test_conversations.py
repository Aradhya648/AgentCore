"""One-off dev cleanup: purge probe / verification / functional-test conversations.

Local dev databases accumulate automated probe runs (``[verify]``, ``[l3-quant]``),
empty-title smoke chats, soft-deleted rows whose ``turn_journal`` was never swept,
and short functional-test threads (``创建测试文件``, ``功能测试``, …). The bulk of
the bloat is ``turn_journal`` (one row per SSE fact); a single probe turn can emit
tens of thousands.

Product discussions whose titles happen to contain「测试」(e.g.「测试方向讨论」) are
**kept** — only obvious automated / functional-test titles match.

Uses ``ConversationRepository.hard_delete`` (messages + cost_events + turn_journal +
memory_updates) plus explicit drops for tables the repo cascade does not yet cover
(turn_metrics, paused_turns, conversation_shares).

Run from ``apps/server``::

    # preview only (default)
    uv run python scripts/cleanup_test_conversations.py

    # actually hard-delete matched conversations
    uv run python scripts/cleanup_test_conversations.py --apply

    # scope to the dev account only
    uv run python scripts/cleanup_test_conversations.py --apply --username dev

    # purge user-trash (soft-deleted) conversations
    uv run python scripts/cleanup_test_conversations.py --purge-soft-deleted
    uv run python scripts/cleanup_test_conversations.py --apply --purge-soft-deleted

    # full dev wipe — purge EVERY conversation (clean slate; irreversible)
    uv run python scripts/cleanup_test_conversations.py --all
    uv run python scripts/cleanup_test_conversations.py --apply --all
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import delete, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.db import async_session_factory
from agentcore.db.models import (
    Conversation,
    ConversationShare,
    CostEvent,
    MemoryUpdateRow,
    Message,
    PausedTurnRow,
    TurnJournalRow,
    TurnMetricsRow,
)
from agentcore.db.repositories import ConversationRepository, UserRepository


def _title_is_probe_or_functional_test(title_col):
    """Title-only heuristics for automated probe / functional-test chats."""
    not_discussion = (
        ~title_col.like("%讨论%")
        & ~title_col.like("%方案%")
        & ~title_col.like("%方向%")
    )
    return (
        title_col.like("[verify%")
        | title_col.like("[l3-quant]%")
        | (title_col == "")
        | title_col.like("创建测试%")
        | (title_col.like("%功能测试%") & not_discussion)
        | (title_col == "测试连接")
        | title_col.like("%worker测试%")
        | (title_col.like("启动%测试%") & not_discussion)
        | (title_col.like("圆桌%测试%") & not_discussion)
        | title_col.like("smoke%")
        | title_col.like("csrf%")
        | title_col.like("me-resume%")
        | (title_col == "时序探针")
        | (title_col == "你好")
        | (title_col == "你是谁")
        | (title_col == "我在")
        | (title_col == "你是什么模型")
        | title_col.like("你好、你是什么模型%")
        | title_col.like("数字%的回应")
        | title_col.like("数字%的含义")
        | title_col.like("P0补测%")
        | title_col.like("给我个提案卡%")
        | title_col.like("初次问候%")
        | (title_col.like("%自我介绍%") & not_discussion)
        | (title_col.like("%问候%") & not_discussion)
        | (title_col == "空工作区")
        | title_col.like("空工作区%")
        | (title_col == "未命名白板")
        | (
            title_col.like("%测试%")
            & not_discussion
        )
    )


def _junk_predicate():
    """SQLAlchemy boolean expression: conversation rows to purge."""
    title = Conversation.title
    probe_or_test = _title_is_probe_or_functional_test(title)
    return probe_or_test


def _soft_deleted_predicate():
    """SQLAlchemy boolean expression: user-trash (soft-deleted) conversations."""
    return Conversation.deleted_at.is_not(None)


def _all_predicate():
    """SQLAlchemy boolean expression: every conversation (full dev wipe).

    Matches both active and soft-deleted rows — used for a clean-slate reset of a
    dev database where all history is throwaway test data.
    """
    return true()


@dataclass(frozen=True)
class _PurgeStats:
    conversations: int
    messages: int
    turn_journal: int
    cost_events: int
    memory_updates: int
    turn_metrics: int
    paused_turns: int
    conversation_shares: int


async def _count_related(session: AsyncSession, conv_ids: list[str]) -> _PurgeStats:
    if not conv_ids:
        return _PurgeStats(0, 0, 0, 0, 0, 0, 0, 0)

    async def _cnt(model, col):
        r = await session.execute(
            select(func.count()).select_from(model).where(col.in_(conv_ids))
        )
        return int(r.scalar_one())

    return _PurgeStats(
        conversations=len(conv_ids),
        messages=await _cnt(Message, Message.conversation_id),
        turn_journal=await _cnt(TurnJournalRow, TurnJournalRow.conversation_id),
        cost_events=await _cnt(CostEvent, CostEvent.conversation_id),
        memory_updates=await _cnt(MemoryUpdateRow, MemoryUpdateRow.conversation_id),
        turn_metrics=await _cnt(TurnMetricsRow, TurnMetricsRow.conversation_id),
        paused_turns=await _cnt(PausedTurnRow, PausedTurnRow.conversation_id),
        conversation_shares=await _cnt(ConversationShare, ConversationShare.conversation_id),
    )


@dataclass(frozen=True)
class _MatchedConversation:
    id: str
    title: str
    message_count: int
    turn_journal_count: int
    deleted_at: str | None = None


async def _list_matched(
    session: AsyncSession,
    *,
    username: str | None,
    purge_soft_deleted: bool,
    all_conversations: bool = False,
) -> list[_MatchedConversation]:
    if all_conversations:
        predicate = _all_predicate()
    elif purge_soft_deleted:
        predicate = _soft_deleted_predicate()
    else:
        predicate = _junk_predicate()
    stmt = (
        select(
            Conversation.id,
            Conversation.title,
            Conversation.deleted_at,
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery(),
            select(func.count())
            .select_from(TurnJournalRow)
            .where(TurnJournalRow.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery(),
        )
        .where(predicate)
        .order_by(
            select(func.count())
            .select_from(TurnJournalRow)
            .where(TurnJournalRow.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
            .desc()
        )
    )
    if username is not None:
        user = await UserRepository(session).get_by_username(username)
        if user is None:
            raise SystemExit(f"unknown username: {username!r}")
        stmt = stmt.where(Conversation.user_id == user.user_id)

    rows = (await session.execute(stmt)).all()
    return [
        _MatchedConversation(
            id=str(r[0]),
            title=r[1] or "",
            message_count=int(r[3]),
            turn_journal_count=int(r[4]),
            deleted_at=r[2].isoformat() if r[2] is not None else None,
        )
        for r in rows
    ]


async def _purge_one(session: AsyncSession, conversation_id: str) -> None:
    await session.execute(
        delete(TurnMetricsRow).where(TurnMetricsRow.conversation_id == conversation_id)
    )
    await session.execute(
        delete(PausedTurnRow).where(PausedTurnRow.conversation_id == conversation_id)
    )
    await session.execute(
        delete(ConversationShare).where(ConversationShare.conversation_id == conversation_id)
    )
    await ConversationRepository(session).hard_delete(conversation_id)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Purge dev probe / test conversations.")
    p.add_argument(
        "--apply",
        action="store_true",
        help="hard-delete matched conversations (default: dry-run only)",
    )
    p.add_argument(
        "--username",
        default=None,
        help="scope to one account (default: all users)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max conversations to delete (debug)",
    )
    p.add_argument(
        "--purge-soft-deleted",
        action="store_true",
        help="purge user-trash rows (deleted_at IS NOT NULL) instead of probe/test junk",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="purge EVERY conversation (full dev wipe; overrides junk/soft filters)",
    )
    return p.parse_args()


def _print_stats(label: str, stats: _PurgeStats) -> None:
    print(f"\n{label}")
    print(f"  conversations:       {stats.conversations}")
    print(f"  messages:            {stats.messages}")
    print(f"  turn_journal:        {stats.turn_journal}")
    print(f"  cost_events:         {stats.cost_events}")
    print(f"  memory_updates:      {stats.memory_updates}")
    print(f"  turn_metrics:        {stats.turn_metrics}")
    print(f"  paused_turns:        {stats.paused_turns}")
    print(f"  conversation_shares: {stats.conversation_shares}")


async def _count_soft_deleted(session: AsyncSession, *, username: str | None) -> int:
    stmt = select(func.count()).select_from(Conversation).where(_soft_deleted_predicate())
    if username is not None:
        user = await UserRepository(session).get_by_username(username)
        if user is None:
            raise SystemExit(f"unknown username: {username!r}")
        stmt = stmt.where(Conversation.user_id == user.user_id)
    return int(await session.scalar(stmt))


async def _count_orphan_journal(session: AsyncSession) -> int:
    """turn_journal rows whose conversation_id no longer exists."""
    conv_ids = select(Conversation.id)
    result = await session.scalar(
        select(func.count())
        .select_from(TurnJournalRow)
        .where(TurnJournalRow.conversation_id.not_in(conv_ids))
    )
    return int(result)


async def _main() -> None:
    args = _parse_args()
    if args.all:
        purge_mode = "ALL conversations (full wipe)"
    elif args.purge_soft_deleted:
        purge_mode = "soft-deleted"
    else:
        purge_mode = "probe/test junk"

    async with async_session_factory() as session:
        before_total = await session.scalar(select(func.count()).select_from(Conversation))
        before_soft = await _count_soft_deleted(session, username=args.username)

        matched = await _list_matched(
            session,
            username=args.username,
            purge_soft_deleted=args.purge_soft_deleted,
            all_conversations=args.all,
        )
        if args.limit is not None:
            matched = matched[: args.limit]

        conv_ids = [row.id for row in matched]
        stats = await _count_related(session, conv_ids)

        mode = "APPLY (hard-delete)" if args.apply else "DRY-RUN (no changes)"
        scope = f"user={args.username!r}" if args.username else "all users"
        print(f"cleanup_test_conversations — {mode} — {scope} — mode={purge_mode}")
        print("\nBefore:")
        print(f"  conversations (all):    {before_total}")
        print(f"  conversations (soft):   {before_soft}")
        _print_stats("Matched rows to purge:", stats)

        print("\nMatched conversations:")
        for row in matched[:50]:
            deleted = f"  deleted_at={row.deleted_at}" if row.deleted_at else ""
            print(
                f"  tj={row.turn_journal_count:>6}  msgs={row.message_count:>3}  "
                f"{row.title!r}  id={row.id}{deleted}"
            )
        if len(matched) > 50:
            print(f"  … and {len(matched) - 50} more")

        if not args.apply:
            print("\nRe-run with --apply to hard-delete.")
            return

        if not conv_ids:
            print("\nNothing to delete.")
            return

        print(f"\nDeleting {len(conv_ids)} conversations …")
        for i, row in enumerate(matched, 1):
            await _purge_one(session, row.id)
            if i % 10 == 0 or i == len(conv_ids):
                print(
                    f"  [{i}/{len(conv_ids)}] last={row.title!r} tj={row.turn_journal_count}"
                )

    # Post-delete verification
    async with async_session_factory() as session:
        remaining = await _list_matched(
            session,
            username=args.username,
            purge_soft_deleted=args.purge_soft_deleted,
            all_conversations=args.all,
        )
        total_conv = await session.scalar(select(func.count()).select_from(Conversation))
        total_tj = await session.scalar(select(func.count()).select_from(TurnJournalRow))
        active_conv = await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.deleted_at.is_(None))
        )
        soft_conv = await _count_soft_deleted(session, username=args.username)
        orphan_tj = await _count_orphan_journal(session)
        print("\nAfter purge:")
        print(f"  conversations (all):          {total_conv}")
        print(f"  conversations (active):       {active_conv}")
        print(f"  conversations (soft):         {soft_conv}")
        print(f"  turn_journal (all):           {total_tj}")
        print(f"  orphan turn_journal (should 0): {orphan_tj}")
        print(f"  still-matched (should 0):     {len(remaining)}")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(130)
