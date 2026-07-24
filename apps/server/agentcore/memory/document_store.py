"""Document-tree-backed :class:`MemoryStore` (Agent记忆与知识系统 §5.7「一处替换收口」).

The MVP long-term memory lived in per-user markdown files (:class:`FileMemoryStore`). The
Document subsystem lands the terminal form: memory is now ``ai_maintained=true`` ``rule`` nodes
in the single ``documents`` tree, addressed exactly as before through the ``MemoryStore`` seam —
``(user_id, path, scope)`` where ``path`` is a note's store-relative name ("画像.md",
"主题/部署.md", "情景/<id>.md", "_memory_meta.json") and ``scope`` is the layer (``None`` =
global, a ``folder_id`` = that project). Because every memory consumer (injection, the two-layer
consolidation, the editor routes, ``remember`` / ``consult_memory``) depends only on this
Protocol, swapping the backing here changes the base for the whole chain — 换底, not a rewrite.

Session strategy: when constructed with a bound ``session`` (the request DI path — routes) all
ops use it, so they run in the caller's transaction / test schema. With no session (the default
``default_memory_store()`` — background consolidation, turn tools) each op opens its own from the
global factory, 照 ``memory/consolidation.py``. CAS stays content-hash (``memory_version``), so
it is store-agnostic and an in-flight editor baseline survived the file→document migration.

``delete`` soft-deletes the tree row AND unlinks the legacy on-disk source under
``data/memory/`` (injectable via ``file_store``), so the startup file→document migration cannot
resurrect a user-deleted note from a leftover markdown file.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import DocumentRepository
from agentcore.memory.store import (
    MEMORY_META_FILE,
    FileMemoryStore,
    MemoryFileMeta,
    MemoryScope,
    default_file_memory_store,
    is_episodic_path,
    is_topic_path,
    memory_version,
)

logger = get_logger(__name__)


def _classify(path: str) -> tuple[str, str]:
    """Map a memory note's store-relative path to its ``(role, apply_mode)`` in the tree.

    The always-injected core (偏好.md / 画像.md) and on-demand topics (主题/*.md) are ``rule``
    docs so they are the injectable / consultable memory (§5.2); topics are ``on_demand`` (name
    rides the directory, not ``<rules>``). Episodic digests (情景/*.md) and the meta sidecar are
    ``general`` — internal consolidation state, never injected, so they stay out of the rule set.
    """
    if is_topic_path(path):
        return "rule", "on_demand"
    if is_episodic_path(path) or path == MEMORY_META_FILE or not path.endswith(".md"):
        return "general", "always"
    return "rule", "always"


class DocumentMemoryStore:
    """A :class:`MemoryStore` over the ``documents`` tree (see module docstring)."""

    def __init__(
        self,
        session: AsyncSession | None = None,
        *,
        file_store: FileMemoryStore | None = None,
    ) -> None:
        self._session = session
        # Optional override of the legacy on-disk source (``data/memory/…``). Production
        # uses ``default_file_memory_store()``; tests inject a tmp-dir store.
        self._file_store = file_store

    def _legacy_file_store(self) -> FileMemoryStore:
        return self._file_store if self._file_store is not None else default_file_memory_store()

    @asynccontextmanager
    async def _repo(self) -> AsyncIterator[DocumentRepository]:
        if self._session is not None:
            yield DocumentRepository(self._session)
        else:
            async with async_session_factory() as session:
                yield DocumentRepository(session)

    async def list(self, user_id: str, scope: MemoryScope = None) -> list[MemoryFileMeta]:
        # Reads DEGRADE to empty on any failure (照 FileMemoryStore's OSError handling) — memory
        # must never break a turn's assembly (§1.6). A non-UUID user_id / transient DB error
        # simply surfaces as「no memory」rather than raising into the pipeline.
        try:
            async with self._repo() as repo:
                notes = await repo.list_memory_notes(user_id, scope)
        except Exception as e:  # noqa: BLE001 - memory read must never break a turn
            logger.warning("memory.list_failed", user_id=user_id, error=str(e))
            return []
        # FileMemoryStore listed only ``*.md`` (rglob) — the meta sidecar is addressed by exact
        # path, never listed. Keep that so callers' path-prefix filters behave identically.
        return [
            MemoryFileMeta(path=n.name, version=memory_version(n.content))
            for n in notes
            if n.name.endswith(".md")
        ]

    async def load(self, user_id: str, path: str, scope: MemoryScope = None) -> str:
        try:
            async with self._repo() as repo:
                note = await repo.get_memory_note(user_id, path, scope)
        except Exception as e:  # noqa: BLE001 - memory read must never break a turn
            logger.warning("memory.load_failed", user_id=user_id, error=str(e))
            return ""
        return note.content if note is not None else ""

    async def save(
        self, user_id: str, path: str, markdown: str, scope: MemoryScope = None
    ) -> None:
        role, apply_mode = _classify(path)
        async with self._repo() as repo:
            await repo.save_memory_note(
                user_id, path, markdown, scope, role=role, apply_mode=apply_mode
            )

    async def delete(self, user_id: str, path: str, scope: MemoryScope = None) -> None:
        async with self._repo() as repo:
            await repo.delete_memory_note(user_id, path, scope)
        # Soft-delete alone leaves the legacy on-disk source intact; the startup
        # file→document migration would then re-INSERT the note. Unlink the source
        # (missing file = silent no-op, 照 FileMemoryStore.delete).
        await self._legacy_file_store().delete(user_id, path, scope)

    async def project_scopes(self, user_id: str) -> list[str]:
        try:
            async with self._repo() as repo:
                return await repo.list_memory_project_scopes(user_id)
        except Exception as e:  # noqa: BLE001 - degrade to no project layers (照 FileMemoryStore)
            logger.warning("memory.project_scopes_failed", user_id=user_id, error=str(e))
            return []
