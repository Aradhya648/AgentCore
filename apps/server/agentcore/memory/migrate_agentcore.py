"""Idempotent layout migration: bare ``记忆/`` + top-level user rules → ``AgentCore/`` (§5.0).

Runs alongside the file→documents migration (``migrate_documents``). Properties:

- **idempotent**: a second run is a no-op once every scope's convention tree holds its
  memory root and user rules.
- **loses no data on failure**: per-scope best-effort — failures are logged and the SOURCE
  nodes are left in place (never deleted), so a failed scope retries next boot.
- **coexists** with file→documents: that pass writes via ``save_memory_note``, which now
  ensures ``AgentCore/记忆/``; this pass cleans up any pre-§5.0 bare roots / top-level rules
  that already lived in the tree. Dual-root fold soft-deletes an empty bare ``记忆/``
  (``deleted_at``); name-clash leftovers keep the bare folder and log.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from agentcore.core.logging import get_logger
from agentcore.db.models import Document
from agentcore.db.repositories.documents import (
    AGENTCORE_ROOT_NAME,
    MEMORY_ROOT_NAME,
    DocumentRepository,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentCoreMigrationStats:
    """Outcome counters for one AgentCore layout migration run."""

    scopes_scanned: int
    memory_roots_moved: int
    rules_moved: int
    scopes_failed: int
    bare_memory_roots_soft_deleted: int = 0


async def _scopes_needing_attention(
    session, user_id: str | None = None
) -> list[tuple[str, str | None]]:
    """Distinct (user_id, folder_id) pairs that still have a bare memory root or top-level rule.

    Also includes scopes that already have an ``AgentCore/`` root so a half-migrated scope
    (AgentCore present, rules still top-level) still gets a pass.
    """
    conditions: list[ColumnElement[bool]] = [
        Document.deleted_at.is_(None),
        Document.kind.in_(("folder", "document")),
    ]
    if user_id is not None:
        conditions.append(Document.user_id == user_id)

    conditions.append(
        or_(
            (
                (Document.parent_id.is_(None))
                & (Document.kind == "folder")
                & (Document.name == MEMORY_ROOT_NAME)
                & (Document.ai_maintained.is_(True))
            ),
            (
                (Document.parent_id.is_(None))
                & (Document.kind == "document")
                & (Document.role == "rule")
                & (Document.ai_maintained.is_(False))
            ),
            (
                (Document.parent_id.is_(None))
                & (Document.kind == "folder")
                & (Document.name == AGENTCORE_ROOT_NAME)
            ),
        )
    )
    result = await session.execute(
        select(Document.user_id, Document.folder_id).where(*conditions).distinct()
    )
    out: list[tuple[str, str | None]] = []
    for uid, fid in result.all():
        out.append((str(uid), str(fid) if fid is not None else None))
    return out


async def _memory_under_agentcore(session, user_id: str, ac_id: str) -> Document | None:
    result = await session.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.parent_id == ac_id,
            Document.kind == "folder",
            Document.ai_maintained.is_(True),
            Document.name == MEMORY_ROOT_NAME,
            Document.deleted_at.is_(None),
        )
    )
    return result.scalars().first()


async def _reparent_children_skip_clash(
    session,
    *,
    user_id: str,
    from_parent_id: str,
    to_parent_id: str,
) -> int:
    """Move live children from one folder to another; skip names that already exist at dest."""
    moved = 0
    children = await session.execute(
        select(Document).where(
            Document.user_id == user_id,
            Document.parent_id == from_parent_id,
            Document.deleted_at.is_(None),
        )
    )
    for child in children.scalars().all():
        clash = await session.execute(
            select(Document).where(
                Document.user_id == user_id,
                Document.parent_id == to_parent_id,
                Document.name == child.name,
                Document.deleted_at.is_(None),
            )
        )
        if clash.scalars().first() is not None:
            logger.warning(
                "memory.migrate_agentcore_note_name_clash",
                user_id=user_id,
                name=child.name,
                doc_id=child.id,
            )
            continue
        child.parent_id = to_parent_id
        moved += 1
    return moved


async def _live_child_count(session, *, user_id: str, parent_id: str) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Document)
        .where(
            Document.user_id == user_id,
            Document.parent_id == parent_id,
            Document.deleted_at.is_(None),
        )
    )
    return int(result.scalar_one())


async def _migrate_scope(
    user_id: str,
    folder_id: str | None,
    session_factory: Callable,
) -> tuple[int, int, int]:
    """Migrate one scope into ``AgentCore/``.

    Returns ``(memory_moved 0|1, rules_moved, bare_soft_deleted 0|1)``.
    """
    memory_moved = 0
    rules_moved = 0
    bare_soft_deleted = 0
    async with session_factory() as session:
        repo = DocumentRepository(session)
        bare = await repo._legacy_bare_memory_root(user_id, folder_id)
        ac = await repo.get_agentcore_root(user_id, folder_id)
        under = await _memory_under_agentcore(session, user_id, ac.id) if ac is not None else None

        if bare is not None and under is None:
            await repo._ensure_memory_root(user_id, folder_id)
            memory_moved = 1
        elif bare is not None and under is not None and bare.id != under.id:
            # Dual roots (race / partial migrate): fold bare children into convention root.
            await _reparent_children_skip_clash(
                session,
                user_id=user_id,
                from_parent_id=bare.id,
                to_parent_id=under.id,
            )
            memory_moved = 1
            logger.warning(
                "memory.migrate_agentcore_dual_memory_roots",
                user_id=user_id,
                folder_id=folder_id,
                bare_id=bare.id,
                under_id=under.id,
            )
            remaining = await _live_child_count(session, user_id=user_id, parent_id=bare.id)
            if remaining == 0:
                # Soft-delete empty bare root (align documents soft-delete; never hard-delete).
                bare.deleted_at = datetime.now()
                bare_soft_deleted = 1
                logger.info(
                    "memory.migrate_agentcore_bare_memory_soft_deleted",
                    user_id=user_id,
                    folder_id=folder_id,
                    bare_id=bare.id,
                    under_id=under.id,
                )
            else:
                logger.warning(
                    "memory.migrate_agentcore_bare_memory_retained",
                    user_id=user_id,
                    folder_id=folder_id,
                    bare_id=bare.id,
                    under_id=under.id,
                    live_children=remaining,
                )

        rules_dir = await repo.ensure_rules_dir(user_id, folder_id)
        for doc in await repo.list_top_level_user_rules(user_id, folder_id):
            clash = await session.execute(
                select(Document).where(
                    Document.user_id == user_id,
                    Document.parent_id == rules_dir.id,
                    Document.name == doc.name,
                    Document.deleted_at.is_(None),
                    Document.id != doc.id,
                )
            )
            if clash.scalars().first() is not None:
                logger.warning(
                    "memory.migrate_agentcore_rule_name_clash",
                    user_id=user_id,
                    folder_id=folder_id,
                    name=doc.name,
                    doc_id=doc.id,
                )
                continue
            doc.parent_id = rules_dir.id
            rules_moved += 1

        await session.commit()
    return memory_moved, rules_moved, bare_soft_deleted


async def migrate_agentcore_layout(
    *,
    session_factory: Callable | None = None,
) -> AgentCoreMigrationStats:
    """Reparent bare ``记忆/`` and top-level user rules into ``AgentCore/{记忆,规则}/``.

    Safe to call repeatedly. Does not delete sources on failure.
    """
    if session_factory is None:
        from agentcore.db.base import async_session_factory as _factory

        session_factory = _factory

    scopes_scanned = memory_roots_moved = rules_moved = scopes_failed = 0
    bare_memory_roots_soft_deleted = 0
    async with session_factory() as session:
        scopes = await _scopes_needing_attention(session)

    for user_id, folder_id in scopes:
        scopes_scanned += 1
        try:
            m, r, soft = await _migrate_scope(user_id, folder_id, session_factory)
            memory_roots_moved += m
            rules_moved += r
            bare_memory_roots_soft_deleted += soft
        except Exception as e:  # noqa: BLE001 - per-scope best-effort
            scopes_failed += 1
            logger.warning(
                "memory.migrate_agentcore_scope_failed",
                user_id=user_id,
                folder_id=folder_id,
                error=str(e),
            )

    stats = AgentCoreMigrationStats(
        scopes_scanned=scopes_scanned,
        memory_roots_moved=memory_roots_moved,
        rules_moved=rules_moved,
        scopes_failed=scopes_failed,
        bare_memory_roots_soft_deleted=bare_memory_roots_soft_deleted,
    )
    logger.info(
        "memory.migrate_agentcore_done",
        scopes_scanned=stats.scopes_scanned,
        memory_roots_moved=stats.memory_roots_moved,
        rules_moved=stats.rules_moved,
        scopes_failed=stats.scopes_failed,
        bare_memory_roots_soft_deleted=stats.bare_memory_roots_soft_deleted,
    )
    return stats
