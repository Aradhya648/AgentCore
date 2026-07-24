"""One-time file→document memory migration (Agent记忆与知识系统 §5.7「一处替换收口」).

The MVP kept long-term memory in per-user markdown files (:class:`FileMemoryStore`); the
Document subsystem lands the terminal form (memory = ``ai_maintained=true`` ``rule`` nodes in
the ``documents`` tree). This pass copies every existing file-backed note into the tree so no
memory is stranded when the backing swaps.

Properties (照 §1.4 迁移先例):
- **one-time + idempotent**: each note is created only if the tree does not already hold it
  (including a soft-deleted row of the same name — user-deleted notes must not resurrect from
  leftover disk files), so a second run is a no-op and a note edited AFTER migration is never
  clobbered.
- **loses no data on failure**: per-user AND per-note best-effort — any failure is logged and
  skipped, and the SOURCE files are NEVER deleted by this pass, so a failed note simply
  migrates next run.

It reads the on-disk layout directly (``<base>/<user>/…`` global, ``<base>/<user>/_folders/
<folder_id>/…`` project) rather than the store API so it can enumerate every user + scope,
including project scopes whose only content is episodic digests / the meta sidecar (which the
store's ``list`` deliberately hides).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agentcore.core.logging import get_logger
from agentcore.db.repositories import DocumentRepository
from agentcore.memory.document_store import _classify
from agentcore.memory.store import MEMORY_META_FILE

logger = get_logger(__name__)

# The reserved subdir under a user's global folder that holds project layers (mirrors
# FileMemoryStore._PROJECT_CONTAINER); its children are ``<folder_id>/`` project scopes.
_PROJECT_CONTAINER = "_folders"


@dataclass(frozen=True)
class DocumentMigrationStats:
    """Outcome counters for one file→document migration run."""

    users_scanned: int
    notes_migrated: int
    notes_skipped_existing: int
    notes_failed: int


def _is_memory_note(rel: str) -> bool:
    """Whether a scope-relative file is a memory note worth migrating (note or meta sidecar)."""
    return rel.endswith(".md") or rel == MEMORY_META_FILE


def _scope_notes(scope_dir: Path, *, is_global: bool) -> list[tuple[str, str]]:
    """(relative-path, body) of every memory note in one scope dir (skips the project container)."""
    out: list[tuple[str, str]] = []
    for path in sorted(scope_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(scope_dir).as_posix()
        # The global scope's dir contains the nested project container — never copy those into
        # the global layer (project scopes are migrated on their own below).
        if is_global and rel.split("/", 1)[0] == _PROJECT_CONTAINER:
            continue
        if not _is_memory_note(rel):
            continue
        try:
            out.append((rel, path.read_text(encoding="utf-8")))
        except OSError as e:
            logger.warning("memory.migrate_read_failed", path=str(path), error=str(e))
    return out


async def _migrate_scope(
    user_id: str,
    scope: str | None,
    notes: list[tuple[str, str]],
    session_factory: Callable,
) -> tuple[int, int, int]:
    """Migrate one (user, scope)'s notes into the tree. Returns (migrated, skipped, failed)."""
    migrated = skipped = failed = 0
    for rel, body in notes:
        try:
            async with session_factory() as session:
                repo = DocumentRepository(session)
                # Soft-deleted same-name rows count as "already recorded" — skip import so a
                # leftover on-disk source cannot resurrect a user-deleted note on restart.
                if (
                    await repo.get_memory_note(user_id, rel, scope, include_deleted=True)
                    is not None
                ):
                    skipped += 1
                    continue
                role, apply_mode = _classify(rel)
                await repo.save_memory_note(
                    user_id, rel, body, scope, role=role, apply_mode=apply_mode
                )
                migrated += 1
        except Exception as e:  # noqa: BLE001 - per-note best-effort; source file is untouched
            failed += 1
            logger.warning(
                "memory.migrate_note_failed",
                user_id=user_id,
                scope=scope or "global",
                path=rel,
                error=str(e),
            )
    return migrated, skipped, failed


async def migrate_file_memory_to_documents(
    *, base_dir: str | Path | None = None, session_factory: Callable | None = None
) -> DocumentMigrationStats:
    """Copy all file-backed memory into the ``documents`` tree (idempotent, best-effort).

    ``base_dir`` defaults to ``<settings.data_dir>/memory`` (the FileMemoryStore root). A missing
    dir means there is nothing to migrate (fresh deploy) → an all-zero result. ``session_factory``
    defaults to the global primary factory; tests inject a per-schema one. Never raises.
    """
    if base_dir is None:
        from agentcore.config import settings

        base_dir = Path(settings.data_dir) / "memory"
    if session_factory is None:
        from agentcore.db.base import async_session_factory

        session_factory = async_session_factory
    base = Path(base_dir)
    if not base.exists():
        return DocumentMigrationStats(0, 0, 0, 0)

    users = 0
    migrated = skipped = failed = 0
    try:
        user_dirs = [p for p in sorted(base.iterdir()) if p.is_dir()]
    except OSError as e:
        logger.warning("memory.migrate_scan_failed", base=str(base), error=str(e))
        return DocumentMigrationStats(0, 0, 0, 0)

    for user_dir in user_dirs:
        user_id = user_dir.name
        users += 1
        try:
            # Global layer: notes directly under the user dir (project container excluded).
            m, s, f = await _migrate_scope(
                user_id, None, _scope_notes(user_dir, is_global=True), session_factory
            )
            migrated, skipped, failed = migrated + m, skipped + s, failed + f
            # Project layers: each ``_folders/<folder_id>/`` subtree.
            container = user_dir / _PROJECT_CONTAINER
            if container.exists():
                for scope_dir in sorted(container.iterdir()):
                    if not scope_dir.is_dir():
                        continue
                    m, s, f = await _migrate_scope(
                        user_id,
                        scope_dir.name,
                        _scope_notes(scope_dir, is_global=False),
                        session_factory,
                    )
                    migrated, skipped, failed = migrated + m, skipped + s, failed + f
        except Exception as e:  # noqa: BLE001 - per-user best-effort; never abort the whole pass
            logger.warning("memory.migrate_user_failed", user_id=user_id, error=str(e))

    stats = DocumentMigrationStats(
        users_scanned=users,
        notes_migrated=migrated,
        notes_skipped_existing=skipped,
        notes_failed=failed,
    )
    if migrated or failed:
        logger.info(
            "memory.migrate_documents_done",
            users=users,
            migrated=migrated,
            skipped=skipped,
            failed=failed,
        )
    return stats
