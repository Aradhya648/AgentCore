"""Document tree data access (「一切皆文档」单表载体, 核心接口定义 §6.2).

One repository over the single ``documents`` table. It serves three consumers that all
share the same rows:

- **Memory store backing**: AI-maintained long-term memory (``ai_maintained=true``) notes
  live under the per-(user, scope) convention tree ``AgentCore/记忆/``, addressed by their
  store-relative ``name`` ("画像.md", "主题/部署.md", …). ``DocumentMemoryStore`` maps the
  ``(user, path, scope)`` seam onto these rows (Agent记忆与知识系统 §5.0 / §5.7).
- **Rule injection**: both user rules (``ai_maintained=false``) and the always-injected memory
  core (``ai_maintained=true``) are ``role='rule', apply_mode='always'`` nodes, gathered per
  scope by ``list_injectable_rules`` for the two-tier ``<rules>`` block (§二). Collection
  stays role + folder_id + apply_mode (not parent-tree walk); when the convention dirs exist,
  results are further restricted to ``AgentCore/规则/`` / ``AgentCore/记忆/`` (bare ``记忆/``
  still accepted for memory during transition). Writes land under ``AgentCore/{规则,记忆}/``.
- **Generic tree CRUD**: the ``/documents`` API creates / reads / renames / moves / deletes any
  node (user rules are just ``role='rule', ai_maintained=false`` documents, §5.2).

All reads filter ``deleted_at IS NULL`` explicitly (this codebase has no global soft-delete
event listener — 照 boards.py / folders.py). Owner scoping is the structural default: mutations
resolve a node owner-scoped so a non-owner id is treated as absent (SEC-002). No DB FK — refs
are app-level ``*_id`` fields (§6.2). CAS is the caller's job (content-hash baseline under the
per-user memory lock, 照 api/routes/memory.py) so the repo stays db-only, no upward import.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from agentcore.core.types import new_id
from agentcore.db.models import Document

from ._base import _UNSET

# Cloud-documents convention root (Agent记忆与知识系统 §5.0). NOT the desktop local default
# path ``~/Documents/AgentCore/`` (workspace container) — same product name, different carrier.
AGENTCORE_ROOT_NAME = "AgentCore"

# User-owned rules directory under the convention root (§5.0 ``AgentCore/规则/``).
RULES_DIR_NAME = "规则"

# AI-memory notes folder under the convention root (§5.0 ``AgentCore/记忆/``). Reserved: a
# user's own folder is ``ai_maintained=false``, so it never collides with this node.
MEMORY_ROOT_NAME = "记忆"

# The canonical user-rule document ``remember`` appends to when the user gives an explicit
# directive (§5.7 用户规则入口①). Additional user-rule docs may be created via the tree API;
# injection gathers them all, this is only the well-known target for the tool path.
USER_RULES_DOC_NAME = "用户规则.md"


def _scope_clause(folder_id: str | None) -> ColumnElement[bool]:
    """WHERE fragment for a scope: NULL = the global layer, else that project's ``folder_id``."""
    if folder_id is None:
        return Document.folder_id.is_(None)
    return Document.folder_id == folder_id


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    # --- AgentCore/ convention tree (§5.0) -----------------------------------------------------

    def _agentcore_root_stmt(self, user_id: str, folder_id: str | None) -> Select:
        return select(Document).where(
            Document.user_id == user_id,
            _scope_clause(folder_id),
            Document.parent_id.is_(None),
            Document.kind == "folder",
            Document.name == AGENTCORE_ROOT_NAME,
            Document.deleted_at.is_(None),
        )

    async def get_agentcore_root(
        self, user_id: str, folder_id: str | None
    ) -> Document | None:
        """The per-scope ``AgentCore/`` convention root, or None if none exists yet."""
        result = await self._session.execute(self._agentcore_root_stmt(user_id, folder_id))
        return result.scalars().first()

    async def ensure_agentcore_root(self, user_id: str, folder_id: str | None) -> Document:
        """Find-or-create the per-scope ``AgentCore/`` convention root (user-visible)."""
        root = await self.get_agentcore_root(user_id, folder_id)
        if root is not None:
            return root
        root = Document(
            id=new_id(),
            user_id=user_id,
            parent_id=None,
            folder_id=folder_id,
            kind="folder",
            role="general",
            ai_maintained=False,
            apply_mode="always",
            name=AGENTCORE_ROOT_NAME,
            content="",
        )
        self._session.add(root)
        await self._session.flush()
        return root

    async def get_rules_dir(self, user_id: str, folder_id: str | None) -> Document | None:
        """The ``AgentCore/规则/`` folder for one scope, or None."""
        ac = await self.get_agentcore_root(user_id, folder_id)
        if ac is None:
            return None
        result = await self._session.execute(
            select(Document).where(
                Document.user_id == user_id,
                Document.parent_id == ac.id,
                Document.kind == "folder",
                Document.name == RULES_DIR_NAME,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def ensure_rules_dir(self, user_id: str, folder_id: str | None) -> Document:
        """Find-or-create ``AgentCore/规则/`` for one scope (user-owned)."""
        existing = await self.get_rules_dir(user_id, folder_id)
        if existing is not None:
            return existing
        ac = await self.ensure_agentcore_root(user_id, folder_id)
        rules = Document(
            id=new_id(),
            user_id=user_id,
            parent_id=ac.id,
            folder_id=folder_id,
            kind="folder",
            role="general",
            ai_maintained=False,
            apply_mode="always",
            name=RULES_DIR_NAME,
            content="",
        )
        self._session.add(rules)
        await self._session.flush()
        return rules

    # --- memory store backing (ai_maintained=true notes under AgentCore/记忆/) ---

    async def _legacy_bare_memory_root(
        self, user_id: str, folder_id: str | None
    ) -> Document | None:
        """Pre-§5.0 bare ``记忆/`` at scope root (``parent_id IS NULL``) — migration source."""
        result = await self._session.execute(
            select(Document).where(
                Document.user_id == user_id,
                _scope_clause(folder_id),
                Document.parent_id.is_(None),
                Document.kind == "folder",
                Document.ai_maintained.is_(True),
                Document.name == MEMORY_ROOT_NAME,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def get_memory_root(self, user_id: str, folder_id: str | None) -> Document | None:
        """The ``记忆`` folder for one (user, scope), or None if none exists yet.

        Prefers ``AgentCore/记忆/``; falls back to a pre-migration bare ``记忆/`` so reads
        keep working until the idempotent layout migration reparents it.
        """
        ac = await self.get_agentcore_root(user_id, folder_id)
        if ac is not None:
            result = await self._session.execute(
                select(Document).where(
                    Document.user_id == user_id,
                    Document.parent_id == ac.id,
                    Document.kind == "folder",
                    Document.ai_maintained.is_(True),
                    Document.name == MEMORY_ROOT_NAME,
                    Document.deleted_at.is_(None),
                )
            )
            under = result.scalars().first()
            if under is not None:
                return under
        return await self._legacy_bare_memory_root(user_id, folder_id)

    async def _ensure_memory_root(self, user_id: str, folder_id: str | None) -> Document:
        """Find-or-create ``AgentCore/记忆/`` (reparents a bare ``记忆/`` when present)."""
        root = await self.get_memory_root(user_id, folder_id)
        ac = await self.ensure_agentcore_root(user_id, folder_id)
        if root is not None:
            if root.parent_id != ac.id:
                # Legacy bare root still at scope top — hoist into the convention tree.
                root.parent_id = ac.id
                await self._session.flush()
            return root
        root = Document(
            id=new_id(),
            user_id=user_id,
            parent_id=ac.id,
            folder_id=folder_id,
            kind="folder",
            role="general",
            ai_maintained=True,
            apply_mode="always",
            name=MEMORY_ROOT_NAME,
            content="",
        )
        self._session.add(root)
        await self._session.flush()
        return root

    async def get_memory_note(
        self,
        user_id: str,
        name: str,
        folder_id: str | None,
        *,
        include_deleted: bool = False,
    ) -> Document | None:
        """One memory note by its store-relative ``name`` under the scope's 记忆 root.

        Live rows only by default. ``include_deleted=True`` also matches soft-deleted
        notes — used by the file→document migration so a user-deleted note is not
        re-imported from a leftover on-disk source (treated as already recorded).
        """
        root = await self.get_memory_root(user_id, folder_id)
        if root is None:
            return None
        conditions: list[ColumnElement[bool]] = [
            Document.user_id == user_id,
            Document.parent_id == root.id,
            Document.name == name,
        ]
        if not include_deleted:
            conditions.append(Document.deleted_at.is_(None))
        result = await self._session.execute(select(Document).where(*conditions))
        return result.scalars().first()

    async def save_memory_note(
        self,
        user_id: str,
        name: str,
        content: str,
        folder_id: str | None,
        *,
        role: str,
        apply_mode: str,
    ) -> Document:
        """Upsert one memory note (creating ``AgentCore/记忆/`` on first write). Unconditional —
        CAS is the caller's job (content-hash baseline under the per-user lock)."""
        root = await self._ensure_memory_root(user_id, folder_id)
        note = await self.get_memory_note(user_id, name, folder_id)
        if note is None:
            note = Document(
                id=new_id(),
                user_id=user_id,
                parent_id=root.id,
                folder_id=folder_id,
                kind="document",
                role=role,
                ai_maintained=True,
                apply_mode=apply_mode,
                name=name,
                content=content,
            )
            self._session.add(note)
        else:
            note.content = content
            note.role = role
            note.apply_mode = apply_mode
        await self._session.commit()
        await self._session.refresh(note)
        return note

    async def delete_memory_note(self, user_id: str, name: str, folder_id: str | None) -> None:
        """Soft-delete one memory note (no-op if it does not exist)."""
        note = await self.get_memory_note(user_id, name, folder_id)
        if note is None:
            return
        note.deleted_at = datetime.now()
        await self._session.commit()

    async def list_memory_notes(self, user_id: str, folder_id: str | None) -> list[Document]:
        """All live memory notes under the scope's 记忆 root (empty when none)."""
        root = await self.get_memory_root(user_id, folder_id)
        if root is None:
            return []
        result = await self._session.execute(
            select(Document)
            .where(
                Document.user_id == user_id,
                Document.parent_id == root.id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.name.asc())
        )
        return list(result.scalars().all())

    async def list_memory_project_scopes(self, user_id: str) -> list[str]:
        """``folder_id``s whose PROJECT memory layer holds a semantic (non-episodic) note.

        Mirrors ``FileMemoryStore.project_scopes``: a project surfaces a「本项目记忆」node
        only where there is a real note to edit — episodic digests / meta sidecars alone do
        not count. Notes carry ``role='rule'`` for the 偏好/画像/主题 core (episodic + meta are
        ``role='general'``), so a rule-role project note is the「has semantic memory」signal.
        """
        result = await self._session.execute(
            select(Document.folder_id)
            .where(
                Document.user_id == user_id,
                Document.folder_id.is_not(None),
                Document.ai_maintained.is_(True),
                Document.role == "rule",
                Document.kind == "document",
                Document.deleted_at.is_(None),
            )
            .distinct()
        )
        return sorted(str(fid) for fid in result.scalars().all() if fid)

    # --- rule injection (memory core + user rules are both role='rule') ---

    async def _injectable_parent_filter(
        self, user_id: str, folder_id: str | None, *, ai_maintained: bool
    ) -> ColumnElement[bool] | None:
        """Restrict injectables to the convention tree when that tree already exists.

        No convention dir → ``None`` (legacy scope-wide collect; avoids half-migration empty
        reads). User rules require ``parent_id == AgentCore/规则/``. Memory always-cores require
        ``AgentCore/记忆/``; a still-live bare ``记忆/`` parent is also accepted (transition /
        name-clash leftovers).
        """
        if ai_maintained:
            ac = await self.get_agentcore_root(user_id, folder_id)
            under: Document | None = None
            if ac is not None:
                result = await self._session.execute(
                    select(Document).where(
                        Document.user_id == user_id,
                        Document.parent_id == ac.id,
                        Document.kind == "folder",
                        Document.ai_maintained.is_(True),
                        Document.name == MEMORY_ROOT_NAME,
                        Document.deleted_at.is_(None),
                    )
                )
                under = result.scalars().first()
            if under is None:
                return None
            bare = await self._legacy_bare_memory_root(user_id, folder_id)
            if bare is not None:
                return or_(Document.parent_id == under.id, Document.parent_id == bare.id)
            return Document.parent_id == under.id

        rules_dir = await self.get_rules_dir(user_id, folder_id)
        if rules_dir is None:
            return None
        return Document.parent_id == rules_dir.id

    async def list_injectable_rules(
        self, user_id: str, folder_id: str | None, *, ai_maintained: bool
    ) -> list[Document]:
        """Always-injected ``rule`` docs of one scope + authorship (§二 two-tier injection).

        ``ai_maintained=True`` → the memory core (偏好.md / 画像.md); ``False`` → the user's own
        rule documents. ``apply_mode='on_demand'`` topics are excluded (they ride the directory,
        not ``<rules>``). Ordered by ``name`` for a stable prefix. When convention dirs exist,
        only nodes under those parents are returned (see ``_injectable_parent_filter``).
        """
        conditions: list[ColumnElement[bool]] = [
            Document.user_id == user_id,
            _scope_clause(folder_id),
            Document.role == "rule",
            Document.apply_mode == "always",
            Document.ai_maintained.is_(ai_maintained),
            Document.kind == "document",
            Document.deleted_at.is_(None),
        ]
        parent_filter = await self._injectable_parent_filter(
            user_id, folder_id, ai_maintained=ai_maintained
        )
        if parent_filter is not None:
            conditions.append(parent_filter)
        result = await self._session.execute(
            select(Document).where(*conditions).order_by(Document.name.asc())
        )
        return list(result.scalars().all())

    # --- user rules (ai_maintained=false, role=rule) ---

    async def get_user_rules_doc(
        self, user_id: str, folder_id: str | None
    ) -> Document | None:
        """The canonical user-rule document for a scope (``remember`` target), or None.

        Prefers a doc under ``AgentCore/规则/``; falls back to any same-name live rule in
        the scope (pre-migration top-level) so append/dedupe keeps working across layout.
        """
        rules_dir = await self.get_rules_dir(user_id, folder_id)
        if rules_dir is not None:
            result = await self._session.execute(
                select(Document).where(
                    Document.user_id == user_id,
                    Document.parent_id == rules_dir.id,
                    Document.role == "rule",
                    Document.ai_maintained.is_(False),
                    Document.name == USER_RULES_DOC_NAME,
                    Document.deleted_at.is_(None),
                )
            )
            under = result.scalars().first()
            if under is not None:
                return under
        result = await self._session.execute(
            select(Document).where(
                Document.user_id == user_id,
                _scope_clause(folder_id),
                Document.role == "rule",
                Document.ai_maintained.is_(False),
                Document.name == USER_RULES_DOC_NAME,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def upsert_user_rules_doc(
        self, user_id: str, folder_id: str | None, content: str
    ) -> Document:
        """Create-or-update the canonical user-rule document under ``AgentCore/规则/``."""
        doc = await self.get_user_rules_doc(user_id, folder_id)
        rules_dir = await self.ensure_rules_dir(user_id, folder_id)
        if doc is None:
            doc = Document(
                id=new_id(),
                user_id=user_id,
                parent_id=rules_dir.id,
                folder_id=folder_id,
                kind="document",
                role="rule",
                ai_maintained=False,
                apply_mode="always",
                name=USER_RULES_DOC_NAME,
                content=content,
            )
            self._session.add(doc)
        else:
            if doc.parent_id != rules_dir.id:
                doc.parent_id = rules_dir.id
            doc.content = content
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def list_top_level_user_rules(
        self, user_id: str, folder_id: str | None
    ) -> list[Document]:
        """Live user-rule docs still at scope root (``parent_id IS NULL``) — migration sources."""
        result = await self._session.execute(
            select(Document)
            .where(
                Document.user_id == user_id,
                _scope_clause(folder_id),
                Document.parent_id.is_(None),
                Document.kind == "document",
                Document.role == "rule",
                Document.ai_maintained.is_(False),
                Document.deleted_at.is_(None),
            )
            .order_by(Document.name.asc())
        )
        return list(result.scalars().all())

    # --- generic tree CRUD (the /documents API; user rules are role=rule docs) ---

    async def create(
        self,
        user_id: str,
        *,
        name: str,
        parent_id: str | None = None,
        folder_id: str | None = None,
        kind: str = "document",
        role: str = "general",
        ai_maintained: bool = False,
        apply_mode: str = "always",
        content: str = "",
    ) -> Document:
        """Create one tree node (folder or document). Caller validates enum values."""
        doc = Document(
            id=new_id(),
            user_id=user_id,
            parent_id=parent_id,
            folder_id=folder_id,
            kind=kind,
            role=role,
            ai_maintained=ai_maintained,
            apply_mode=apply_mode,
            name=name,
            content=content,
        )
        self._session.add(doc)
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def get(self, document_id: str, *, user_id: str) -> Document | None:
        """Owner-scoped fetch (non-owner / unknown id → None → route 404; SEC-002)."""
        result = await self._session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == user_id,
                Document.deleted_at.is_(None),
            )
        )
        return result.scalars().first()

    async def list_children(
        self, user_id: str, *, parent_id: str | None
    ) -> list[Document]:
        """A folder's direct children (``parent_id`` None = the user's top-level nodes)."""
        stmt = select(Document).where(
            Document.user_id == user_id,
            Document.deleted_at.is_(None),
        )
        stmt = stmt.where(
            Document.parent_id.is_(None) if parent_id is None else Document.parent_id == parent_id
        )
        result = await self._session.execute(stmt.order_by(Document.name.asc()))
        return list(result.scalars().all())

    async def update_content(
        self, document_id: str, *, user_id: str, content: str
    ) -> Document | None:
        """Overwrite a document's body (unconditional; CAS is the caller's job)."""
        doc = await self.get(document_id, user_id=user_id)
        if doc is None:
            return None
        doc.content = content
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def rename(self, document_id: str, *, user_id: str, name: str) -> Document | None:
        doc = await self.get(document_id, user_id=user_id)
        if doc is None:
            return None
        doc.name = name
        await self._session.commit()
        await self._session.refresh(doc)
        return doc

    async def _descendant_ids(self, user_id: str, root_id: str) -> list[str]:
        """All live descendant ids of a node (BFS), so a folder delete cascades its subtree."""
        ids: list[str] = []
        frontier = [root_id]
        while frontier:
            result = await self._session.execute(
                select(Document.id).where(
                    Document.user_id == user_id,
                    Document.parent_id.in_(frontier),
                    Document.deleted_at.is_(None),
                )
            )
            children = [row for row in result.scalars().all()]
            ids.extend(children)
            frontier = children
        return ids

    async def soft_delete(self, document_id: str, *, user_id: str) -> bool:
        """Soft-delete a node and (for a folder) its whole subtree. Idempotent."""
        doc = await self.get(document_id, user_id=user_id)
        if doc is None:
            return False
        now = datetime.now()
        doc.deleted_at = now
        for child_id in await self._descendant_ids(user_id, document_id):
            child = await self._session.get(Document, child_id)
            if child is not None and child.deleted_at is None:
                child.deleted_at = now
        await self._session.commit()
        return True

    async def move(
        self,
        document_id: str,
        *,
        user_id: str,
        parent_id: str | None,
        folder_id: str | None | object = _UNSET,
    ) -> Document | None:
        """Reparent a node (and optionally rescope it).

        ``folder_id`` uses the ``_UNSET`` sentinel (照 boards.update_meta) so an omitted value
        leaves the scope alone while an explicit ``None`` moves the node to the global layer.
        """
        doc = await self.get(document_id, user_id=user_id)
        if doc is None:
            return None
        doc.parent_id = parent_id
        if folder_id is not _UNSET:
            doc.folder_id = folder_id  # type: ignore[assignment]
        await self._session.commit()
        await self._session.refresh(doc)
        return doc
