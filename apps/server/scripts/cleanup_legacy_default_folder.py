"""One-off dev cleanup: retire the legacy「我的工作区」default local folder.

Before 工作区对称化 (D1a), the desktop pre-seeded **one** shared local folder
named「我的工作区」(bound to the container root ``~/Documents/AgentCore``) and
routed every local chat into it. That model is gone: a desktop 裸聊 now lazily
promotes its own per-conversation local folder (container root + ``local_subpath``),
symmetric with cloud bare-chat promotion. Existing dev databases may still carry the
old「我的工作区」row, which now shows up as a stale card in ``/files``.

This prunes those rows. It is a **dev convenience** (产品负责人 confirmed 存量 is
ignored → no production migration); it only touches the database — on-disk files
under the container are left for the user to clean.

Matched folder = a *live, local, root-bound* folder (``local_root_id`` set,
``local_subpath`` empty/NULL → it bound the container ROOT, not a per-conversation
subpath) whose ``name`` equals ``--name`` (default「我的工作区」). Per the app's own
``FolderRepository.soft_delete`` convention, each matched folder's conversations are
first re-parented to ungrouped (``folder_id`` → NULL) so no chat is lost — they
become 裸聊 again and re-promote to their own local folder on the next file write.

CAVEAT: a folder a user *deliberately* named「我的工作区」would also match
(structurally identical). Always eyeball the dry-run preview (it prints id / owner /
root_id / conversation counts) before passing ``--apply``.

Run from ``apps/server``::

    # preview only (default): list what WOULD be pruned, change nothing
    uv run python scripts/cleanup_legacy_default_folder.py

    # actually prune (hard-delete the rows) across all users
    uv run python scripts/cleanup_legacy_default_folder.py --apply

    # soft-delete instead (set deleted_at, reversible), scoped to one account
    uv run python scripts/cleanup_legacy_default_folder.py --apply --soft --username dev

    # also purge rows already soft-deleted, and match a custom name
    uv run python scripts/cleanup_legacy_default_folder.py --apply --include-deleted --name "My Workspace"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from sqlalchemy import func, select, update

from agentcore.db import async_session_factory
from agentcore.db.models import Conversation, Folder
from agentcore.db.repositories import UserRepository

DEFAULT_NAME = "我的工作区"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Prune the legacy「我的工作区」default local folder (dev cleanup).",
    )
    p.add_argument(
        "--name",
        default=DEFAULT_NAME,
        help="folder name to match (default: 我的工作区)",
    )
    p.add_argument(
        "--username",
        default=None,
        help="scope to a single account (default: all users)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="perform the deletion (default: dry-run preview only)",
    )
    p.add_argument(
        "--soft",
        action="store_true",
        help="soft-delete (set deleted_at, reversible) instead of hard-delete",
    )
    p.add_argument(
        "--include-deleted",
        action="store_true",
        help="also match folders already soft-deleted (purge them)",
    )
    return p.parse_args()


async def _count_conversations(session, folder_id: str) -> tuple[int, int]:
    """Return ``(live, total)`` conversation counts bound to ``folder_id``."""
    total = await session.scalar(
        select(func.count()).select_from(Conversation).where(Conversation.folder_id == folder_id)
    )
    live = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.folder_id == folder_id,
            Conversation.deleted_at.is_(None),
        )
    )
    return int(live or 0), int(total or 0)


async def _run(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        # Safety filter: live (unless --include-deleted), LOCAL (root bound), and
        # subpath-less → the OLD default that bound the container root itself, never a
        # per-conversation promoted folder (those carry a non-empty local_subpath).
        conditions = [
            Folder.name == args.name,
            Folder.local_root_id.is_not(None),
            func.coalesce(Folder.local_subpath, "") == "",
        ]
        if not args.include_deleted:
            conditions.append(Folder.deleted_at.is_(None))

        if args.username:
            user = await UserRepository(session).get_by_username(args.username)
            if user is None:
                print(f"user {args.username!r} not found", file=sys.stderr)
                raise SystemExit(1)
            conditions.append(Folder.user_id == user.user_id)

        folders = (
            (
                await session.execute(
                    select(Folder).where(*conditions).order_by(Folder.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        if not folders:
            print(f"no folders match name={args.name!r} — nothing to do.")
            return

        mode = "soft-delete" if args.soft else "HARD-delete"
        verb = "Pruning" if args.apply else "Would prune"
        print(f"{verb} {len(folders)} folder(s) ({mode}):\n")

        total_convs = 0
        for f in folders:
            live, total = await _count_conversations(session, f.id)
            total_convs += total
            deleted_tag = " [already soft-deleted]" if f.deleted_at else ""
            print(f"  • {f.name!r}  id={f.id}{deleted_tag}")
            print(f"      owner={f.user_id}")
            print(f"      root_id={f.local_root_id!r}  subpath={f.local_subpath!r}")
            print(f"      conversations: {live} live / {total} total → unbound to 裸聊")

        if not args.apply:
            print(
                "\n[dry-run] no changes made. Re-run with --apply to prune "
                "(add --soft to keep them recoverable)."
            )
            return

        for f in folders:
            # Re-parent ALL conversations (incl. soft-deleted) so no folder_id dangles.
            await session.execute(
                update(Conversation).where(Conversation.folder_id == f.id).values(folder_id=None)
            )
            if args.soft:
                f.deleted_at = datetime.now()
            else:
                await session.delete(f)

        await session.commit()
        print(
            f"\ndone: {len(folders)} folder(s) {mode}d, "
            f"{total_convs} conversation(s) re-parented to ungrouped."
        )


if __name__ == "__main__":
    asyncio.run(_run(_parse_args()))
