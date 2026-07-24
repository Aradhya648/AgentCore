"""Migrate folder workspaces to per-conversation scratch spaces (Folder refactor).

One-off migration (folder-refactor-design §7): auto-promote folders with a single
conversation get their workspace files moved to ``conv/<conversation_id>/``, local
bindings copied onto the conversation, the folder soft-deleted, and project-scoped
memory merged into global. Multi-conversation folders are marked legacy and left
untouched (Phase 2).

Run from ``apps/server``::

    uv run python scripts/migrate_folder_workspaces.py --dry-run   # preview plan
    uv run python scripts/migrate_folder_workspaces.py             # execute migration
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from agentcore.config import settings
from agentcore.db import async_session_factory
from agentcore.db.models import Folder
from agentcore.db.repositories import ConversationRepository, FolderRepository
from agentcore.memory.store import _PROJECT_CONTAINER
from agentcore.workspace.locate import workspace_has_entries, workspace_root_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migrate folder workspaces to per-conversation scratch spaces.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the migration plan without making changes",
    )
    return p.parse_args()


def _memory_project_dir(user_id: str, folder_id: str) -> Path:
    return Path(settings.data_dir) / "memory" / user_id / _PROJECT_CONTAINER / folder_id


def _memory_global_dir(user_id: str) -> Path:
    return Path(settings.data_dir) / "memory" / user_id


def _project_memory_has_files(project_dir: Path) -> bool:
    return project_dir.is_dir() and any(project_dir.rglob("*.md"))


def _merge_folder_memory_to_global(
    user_id: str, folder_id: str, *, dry_run: bool
) -> bool:
    """Merge ``<user>/_folders/<folder_id>/`` notes into the global layer."""
    project_dir = _memory_project_dir(user_id, folder_id)
    if not _project_memory_has_files(project_dir):
        return False

    if dry_run:
        return True

    global_dir = _memory_global_dir(user_id)
    global_dir.mkdir(parents=True, exist_ok=True)

    for src_file in sorted(project_dir.rglob("*.md")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(project_dir)
        dst_file = global_dir / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        incoming = src_file.read_text(encoding="utf-8")
        if dst_file.exists():
            existing = dst_file.read_text(encoding="utf-8")
            merged = f"{existing.rstrip()}\n\n---\n\n{incoming}".strip() + "\n"
            dst_file.write_text(merged, encoding="utf-8")
            src_file.unlink()
        else:
            shutil.move(str(src_file), str(dst_file))

    shutil.rmtree(project_dir, ignore_errors=True)
    return True


def _move_workspace(
    *,
    user_id: str,
    folder_id: str,
    conversation_id: str,
    dry_run: bool,
) -> str:
    """Move folder workspace files to the conversation scratch path.

    Returns one of: ``moved``, ``skip_already``, ``skip_empty``, ``error_collision``.
    """
    src = workspace_root_path(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    dst = workspace_root_path(
        user_id=user_id, folder_id=None, conversation_id=conversation_id
    )

    src_has_files = workspace_has_entries(
        user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
    )
    dst_has_files = workspace_has_entries(
        user_id=user_id, folder_id=None, conversation_id=conversation_id
    )

    if not src_has_files:
        return "skip_already" if dst_has_files else "skip_empty"

    if dst_has_files:
        return "error_collision"

    if dry_run:
        print(f"MOVE: {src} → {dst}")
        return "moved"

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return "moved"


@dataclass
class MigrationStats:
    moved: int = 0
    legacy: int = 0
    skipped: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


async def _migrate_auto_promote_folder(
    session,
    folder: Folder,
    conversation_id: str,
    *,
    dry_run: bool,
    stats: MigrationStats,
) -> None:
    user_id = folder.user_id
    folder_id = folder.id

    try:
        move_result = _move_workspace(
            user_id=user_id,
            folder_id=folder_id,
            conversation_id=conversation_id,
            dry_run=dry_run,
        )
        if move_result == "moved":
            stats.moved += 1
        elif move_result == "error_collision":
            msg = (
                f"folder {folder_id}: destination workspace already has files "
                f"(conv {conversation_id})"
            )
            print(f"ERROR: {msg}")
            stats.errors += 1
            stats.error_details.append(msg)
            return
        elif move_result == "skip_already":
            print(f"SKIP_MOVE: workspace already at conv/{conversation_id} (folder {folder_id})")
        else:
            print(f"SKIP_MOVE: no files at workspaces/{user_id}/{folder_id}/")

        has_local_binding = bool(folder.local_root_id) or bool(folder.local_subpath)
        if has_local_binding:
            root_id = folder.local_root_id
            subpath = folder.local_subpath
            if dry_run:
                print(
                    f"BIND: conversation {conversation_id} "
                    f"← root={root_id!r} subpath={subpath!r}"
                )
            else:
                await ConversationRepository(session).set_local_binding(
                    conversation_id,
                    root_id=root_id,
                    subpath=subpath,
                )

        project_mem = _memory_project_dir(user_id, folder_id)
        if _project_memory_has_files(project_mem):
            if dry_run:
                print(f"MERGE_MEMORY: {folder_id} → global")
            elif _merge_folder_memory_to_global(user_id, folder_id, dry_run=False):
                print(f"MERGE_MEMORY: {folder_id} → global (done)")

        if dry_run:
            print(f"UNLINK: conversation {conversation_id}.folder_id = NULL")
            print(f"DELETE: folder {folder_id}")
        else:
            deleted = await FolderRepository(session).soft_delete(
                folder_id, user_id=user_id
            )
            if not deleted:
                existing = await FolderRepository(session).get_by_id_unscoped(folder_id)
                if existing is None:
                    msg = f"folder {folder_id}: soft-delete failed (row missing)"
                    print(f"ERROR: {msg}")
                    stats.errors += 1
                    stats.error_details.append(msg)
                    return
                if existing.deleted_at is not None:
                    print(f"SKIP_DELETE: folder {folder_id} already soft-deleted")
                else:
                    msg = f"folder {folder_id}: soft-delete failed (owner mismatch?)"
                    print(f"ERROR: {msg}")
                    stats.errors += 1
                    stats.error_details.append(msg)
                    return

    except Exception as exc:
        await session.rollback()
        msg = f"folder {folder_id}: {exc}"
        print(f"ERROR: {msg}")
        traceback.print_exc()
        stats.errors += 1
        stats.error_details.append(msg)


async def _run(args: argparse.Namespace) -> None:
    stats = MigrationStats()
    mode = "DRY-RUN" if args.dry_run else "EXECUTE"
    print(f"=== migrate_folder_workspaces ({mode}) ===")
    print(f"data_dir: {settings.data_dir}\n")

    async with async_session_factory() as session:
        folders = (
            (
                await session.execute(
                    select(Folder)
                    .where(Folder.deleted_at.is_(None))
                    .order_by(Folder.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        if not folders:
            print("no live folders found — nothing to do.")
            return

        print(f"scanning {len(folders)} live folder(s)…\n")

        conv_repo = ConversationRepository(session)

        for folder in folders:
            conv_ids = await conv_repo.list_ids_by_folder(folder.id, user_id=folder.user_id)
            n = len(conv_ids)

            if n == 0:
                print(
                    f"SKIP: folder {folder.id} ({folder.name!r}) — "
                    "no live conversations"
                )
                stats.skipped += 1
                continue

            if n > 1:
                print(
                    f"LEGACY: folder {folder.id} ({folder.name!r}) has {n} conversations "
                    "— skipped (Phase 2)"
                )
                stats.legacy += 1
                continue

            conversation_id = conv_ids[0]
            print(
                f"AUTO-PROMOTE: folder {folder.id} ({folder.name!r}) "
                f"→ conv {conversation_id}"
            )
            await _migrate_auto_promote_folder(
                session,
                folder,
                conversation_id,
                dry_run=args.dry_run,
                stats=stats,
            )
            print()

    print("=== summary ===")
    print(f"  moved:   {stats.moved}")
    print(f"  legacy:  {stats.legacy}")
    print(f"  skipped: {stats.skipped}")
    print(f"  errors:  {stats.errors}")
    if stats.error_details:
        print("\nerror details:")
        for detail in stats.error_details:
            print(f"  • {detail}")

    if args.dry_run:
        print("\n[dry-run] no changes made. Re-run without --dry-run to execute.")

    if stats.errors:
        raise SystemExit(1)


def main() -> None:
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
