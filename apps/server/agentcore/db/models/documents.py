"""Document subsystem model (「一切皆文档」单表载体).

The Document subsystem is a single content tree that holds every AI-context artifact —
user rules, AI-maintained long-term memory, and ordinary documents — as rows in ONE
``documents`` table (Agent记忆与知识系统 §五 / 核心接口定义 §6.2「文件模型单表设计」). It is
not three tables: rule / memory / knowledge are the SAME entity (a markdown document) taking
different values on three orthogonal metadata axes:

- ``ai_maintained`` (§5.2 谁写): ``false`` = a user-owned rule the AI may draft but never
  silently rewrite; ``true`` = AI-maintained long-term memory. A ``rule``-role document is a
  「用户规则」when ``ai_maintained=false`` and「AI 记忆」when ``true`` — same carrier, same
  injection, distinguished only by this flag (the code-level safety branch for「谁可静默改写」).
- scope (§5.3 位置即作用域): carried by ``folder_id`` for this phase — ``NULL`` = the user's
  global root (injected into every conversation), a workspace ``Folder`` id = that project's
  layer (injected only for conversations bound to it). The workspace ``Folder`` is not yet a
  node in this tree (that unification is a later cut), so ``folder_id`` bridges「位置」the same
  way ``boards``/``conversations`` carry it — an app-level ref, no DB FK (§6.2).
- ``apply_mode`` (§5.4 注入策略): ``always`` (full body rides ``<rules>``), ``on_demand`` (only
  the name rides the prompt; the body is pulled by a consult tool), ``conditional`` (reserved —
  not driven this phase, §5.7「第一期不做」).

``parent_id`` is the intra-tree parent (a folder node's children); ``kind`` is the node type
(folder / document; ``upload`` / ``base`` reserved by the CheckConstraint for forward-compat).
Every node also denormalizes its ``folder_id`` scope so a scope query is a flat column filter,
never a tree walk. Soft-deleted (``deleted_at``) and content-addressed for CAS via a SHA-256 of
the body (``memory.memory_version``) — no version counter, so the tag is store-agnostic and
survives the file→document migration (Agent记忆与知识系统 §1.4「每文件 CAS」).
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid

# Node types (核心接口定义 §6.2). Phase 1 uses folder / document; upload / base are reserved
# in the CheckConstraint so a later cut (uploads, the workspace base node) needs no schema churn.
DOCUMENT_KINDS = ("folder", "document", "upload", "base")
# AI-context roles (§5.2). ``rule`` (user rule XOR AI memory, split by ``ai_maintained``),
# ``general`` (ordinary document / memory sidecar), ``attachment`` reserved.
DOCUMENT_ROLES = ("rule", "general", "attachment")
# Injection strategies (§5.4). ``conditional`` reserved (no trigger substrate this phase, §5.7).
DOCUMENT_APPLY_MODES = ("always", "conditional", "on_demand")


class Document(Base):
    """One node in the user's Document tree (folder or content document).

    A ``rule``-role, ``ai_maintained=false`` document is a user rule; ``ai_maintained=true`` is
    AI memory — same table, same injection pipeline. Ordinary documents are ``general``. The
    tree is per-user; ``parent_id`` gives structure and ``folder_id`` gives the injection scope
    (NULL = global). No DB ForeignKey — references are app-level ``*_id`` fields (§6.2).
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "kind in ('folder', 'document', 'upload', 'base')",
            name="ck_documents_kind",
        ),
        CheckConstraint(
            "role in ('rule', 'general', 'attachment')",
            name="ck_documents_role",
        ),
        CheckConstraint(
            "apply_mode in ('always', 'conditional', 'on_demand')",
            name="ck_documents_apply_mode",
        ),
        # Tree navigation ("children of a folder") + the memory store's per-scope note
        # lookups (all keyed by (user_id, parent_id)).
        Index("ix_documents_user_parent", "user_id", "parent_id"),
        # Scope-wide reads: rule injection (WHERE user_id, folder_id, role, apply_mode) and
        # the project-memory rail (distinct folder_id). folder_id NULL = the global layer.
        Index("ix_documents_user_folder", "user_id", "folder_id"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), nullable=False)
    # Intra-tree parent (app-level FK). NULL = a top-level node of its scope (the user's
    # cloud root for the global layer, §5.3). A folder node's children carry its id here.
    parent_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False), nullable=True)
    # Injection scope (位置即作用域, §5.3): NULL = global (every conversation); a workspace
    # ``Folder`` id = that project's layer. Denormalized onto every node so a scope query is a
    # flat filter. App-level FK; cleared/ignored if the folder is gone (no cascade lock).
    folder_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=False), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'document'")
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'general'")
    )
    # §5.2 谁写：false = user-owned rule (AI may draft, never silently rewrite); true = AI
    # long-term memory. The load-bearing safety flag — memory maintenance ONLY ever writes
    # ai_maintained=true nodes, never a user's rule.
    ai_maintained: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    apply_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'always'")
    )
    # Node name within its parent. For memory notes this is the store-relative path
    # (e.g. "画像.md", "主题/部署.md") so the (user, path, scope) seam maps 1:1 to a row.
    name: Mapped[str] = mapped_column(String(500), nullable=False, server_default=text("''"))
    # Markdown body ("" for folder nodes). CAS is a SHA-256 of these bytes computed on read
    # (memory.memory_version) — store-agnostic, so a manual edit and an offline pass conflict
    # exactly as they did on the file store.
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=datetime.now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
