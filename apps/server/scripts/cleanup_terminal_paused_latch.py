"""One-off dev cleanup: clear stale ``usage.paused`` on terminal assistant rows.

Root cause (fixed in ``merge_usage_status``): pause snapshots wrote ``paused:true``;
terminal finalize popped it, but ``upsert_assistant(merge=True)`` re-merged
``{**existing, **incoming}`` and resurrected the latch → ``status=complete`` +
``paused=true``. Cold load then showed「已暂停」.

This script only removes the ``paused`` key from ``messages.usage`` JSON when the
merged status is already terminal (complete / incomplete / failed). It does **not**
delete rows or wipe conversations.

Dev convenience only (开发期无真实用户数据). Preview by default; pass ``--apply``
to write.

Run from ``apps/server``::

    uv run python scripts/cleanup_terminal_paused_latch.py
    uv run python scripts/cleanup_terminal_paused_latch.py --apply
    uv run python scripts/cleanup_terminal_paused_latch.py --conversation deb4f5ca-beaf-4b59-9761-f09bfd8e5710 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from sqlalchemy import select

from agentcore.conversation.store.merge import is_terminal_status
from agentcore.db import async_session_factory
from agentcore.db.models import Message


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Clear stale usage.paused on terminal assistant messages (dev cleanup).",
    )
    p.add_argument(
        "--conversation",
        help="Limit to one conversation_id (UUID).",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default is dry-run preview).",
    )
    return p.parse_args()


def _usage_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _is_dirty(usage: dict[str, Any]) -> bool:
    if usage.get("paused") is not True:
        return False
    status = usage.get("status")
    return is_terminal_status(status) if status else False


async def _run(*, conversation_id: str | None, apply: bool) -> int:
    async with async_session_factory() as session:
        stmt = select(Message).where(Message.role == "assistant")
        if conversation_id:
            stmt = stmt.where(Message.conversation_id == conversation_id)
        rows = (await session.execute(stmt)).scalars().all()

        dirty: list[Message] = []
        for row in rows:
            usage = _usage_dict(row.usage)
            if _is_dirty(usage):
                dirty.append(row)

        print(f"scanned={len(rows)} dirty={len(dirty)} apply={apply}")
        for row in dirty:
            usage = _usage_dict(row.usage)
            print(
                f"  {row.id} conv={row.conversation_id} "
                f"status={usage.get('status')} paused={usage.get('paused')}"
            )
            if apply:
                cleaned = dict(usage)
                cleaned.pop("paused", None)
                row.usage = cleaned

        if apply and dirty:
            await session.commit()
            print(f"cleared paused on {len(dirty)} row(s)")
        elif not apply and dirty:
            print("dry-run only; re-run with --apply to write")
        return len(dirty)


def main() -> None:
    args = _parse_args()
    n = asyncio.run(_run(conversation_id=args.conversation, apply=args.apply))
    # Non-zero exit when dry-run finds dirt is useful in CI-ish checks; keep 0 for apply.
    if not args.apply and n:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
