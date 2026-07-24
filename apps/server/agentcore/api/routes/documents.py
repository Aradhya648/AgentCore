"""Document tree CRUD API (「一切皆文档」子系统第一期, Agent记忆与知识系统 §5.7 载体).

Self-only CRUD over the single ``documents`` content tree. This is the generic tree surface a
future「文件」page drives; in this phase its load-bearing use is **user rules** — a user rule is
just a ``role='rule'`` document with ``ai_maintained=false`` (§5.2), created / edited / deleted
here, then injected ahead of AI memory with authoritative wording (§二 两档措辞).

Ownership is the structural default (every op is owner-scoped → a non-owner id 404s, SEC-002).
Nodes created here are always ``ai_maintained=false``: AI-maintained memory is written by the
consolidation pass / memory routes, never authored as「AI 记忆」through this user-facing API.
CAS mirrors the memory editor — a content write carries a content-hash ``baseline`` and reports a
conflict instead of clobbering. ``conditional`` apply_mode is not offered (§5.7 第一期不做).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agentcore.api.dependencies import AuthUser, get_document_repo
from agentcore.db.models import Document
from agentcore.db.repositories import DocumentRepository
from agentcore.memory import memory_version

router = APIRouter(prefix="/documents", tags=["documents"])

# What a user may author via this API (§5.2). AI memory (ai_maintained=true) is not user-settable
# here, and every user rule is ``apply_mode='always'``: rule ``on_demand`` + ``consult_rule`` and
# scene ``conditional`` are explicitly out of the first phase (§5.7 第一期不做), so the field is
# not exposed. (``on_demand`` still exists internally for AI memory topics, set by the store.)
DocKind = Literal["folder", "document"]
DocRole = Literal["rule", "general"]


class DocumentNodeView(BaseModel):
    """A tree node's metadata (list rows — body omitted so a listing stays light)."""

    id: str
    parent_id: str | None
    folder_id: str | None
    kind: str
    role: str
    ai_maintained: bool
    apply_mode: str
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentDetailView(DocumentNodeView):
    """A node plus its markdown body and content-hash CAS tag (the editor's load payload)."""

    content: str
    version: str


class DocumentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    kind: DocKind = "document"
    role: DocRole = "general"
    content: str = ""
    # ``parent_id`` None = a top-level node of its scope — except ``role='rule'`` documents,
    # which are auto-parented under ``AgentCore/规则/`` (§5.0 新写入落点). When ``parent_id``
    # is set, the child inherits the parent's ``folder_id`` scope; ``folder_id`` is only
    # honored at root (and for the rule auto-parent path).
    parent_id: str | None = None
    folder_id: str | None = None


class DocumentContentRequest(BaseModel):
    content: str
    # The version the edit was based on; None writes unconditionally (照 memory.py).
    baseline: str | None = None


class DocumentWriteResult(BaseModel):
    ok: bool
    version: str
    conflict: bool = False


class DocumentPatchRequest(BaseModel):
    """Rename and/or reparent a node (content untouched — that goes through PUT)."""

    name: str | None = Field(default=None, min_length=1, max_length=500)
    # Use the string "" wrapped by the caller? No — reparent semantics: omitted = leave alone.
    parent_id: str | None = None
    reparent: bool = False  # set True to apply parent_id (even to None = move to root)


def _detail(doc: Document) -> DocumentDetailView:
    return DocumentDetailView(
        id=doc.id,
        parent_id=doc.parent_id,
        folder_id=doc.folder_id,
        kind=doc.kind,
        role=doc.role,
        ai_maintained=doc.ai_maintained,
        apply_mode=doc.apply_mode,
        name=doc.name,
        content=doc.content,
        version=memory_version(doc.content),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=list[DocumentNodeView])
async def list_documents(
    user: AuthUser,
    parent_id: str | None = None,
    repo: DocumentRepository = Depends(get_document_repo),
) -> list[DocumentNodeView]:
    """List a folder's direct children (``parent_id`` omitted = the user's top-level nodes)."""
    nodes = await repo.list_children(user.user_id, parent_id=parent_id)
    return [DocumentNodeView.model_validate(n) for n in nodes]


@router.post("", response_model=DocumentDetailView)
async def create_document(
    body: DocumentCreateRequest,
    user: AuthUser,
    repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentDetailView:
    """Create a tree node (always ``ai_maintained=false`` — user-owned).

    A child inherits its parent's ``folder_id`` scope; a root node takes the requested scope.
    New ``role='rule'`` documents with no parent land under ``AgentCore/规则/`` (§5.0).
    """
    folder_id = body.folder_id
    parent_id = body.parent_id
    if parent_id is not None:
        parent = await repo.get(parent_id, user_id=user.user_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="parent not found")
        if parent.kind != "folder":
            raise HTTPException(status_code=400, detail="parent is not a folder")
        folder_id = parent.folder_id
    elif body.role == "rule" and body.kind == "document":
        # Convention write path: user rules never sit bare at the scope root.
        rules_dir = await repo.ensure_rules_dir(user.user_id, folder_id)
        parent_id = rules_dir.id
        folder_id = rules_dir.folder_id
    doc = await repo.create(
        user.user_id,
        name=body.name,
        parent_id=parent_id,
        folder_id=folder_id,
        kind=body.kind,
        role=body.role,
        ai_maintained=False,
        apply_mode="always",
        content=body.content if body.kind == "document" else "",
    )
    return _detail(doc)


@router.get("/{document_id}", response_model=DocumentDetailView)
async def get_document(
    document_id: str,
    user: AuthUser,
    repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentDetailView:
    doc = await repo.get(document_id, user_id=user.user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return _detail(doc)


@router.put("/{document_id}", response_model=DocumentWriteResult)
async def update_document_content(
    document_id: str,
    body: DocumentContentRequest,
    user: AuthUser,
    repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentWriteResult:
    """Overwrite a document's body (CAS-guarded; conflict instead of clobber, 照 memory.py)."""
    doc = await repo.get(document_id, user_id=user.user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    current_version = memory_version(doc.content)
    if body.baseline is not None and body.baseline != current_version:
        return DocumentWriteResult(ok=False, version=current_version, conflict=True)
    await repo.update_content(document_id, user_id=user.user_id, content=body.content)
    return DocumentWriteResult(ok=True, version=memory_version(body.content))


@router.patch("/{document_id}", response_model=DocumentDetailView)
async def patch_document(
    document_id: str,
    body: DocumentPatchRequest,
    user: AuthUser,
    repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentDetailView:
    """Rename and/or reparent a node (set ``reparent`` to apply ``parent_id``)."""
    doc = await repo.get(document_id, user_id=user.user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if body.name is not None:
        await repo.rename(document_id, user_id=user.user_id, name=body.name)
    if body.reparent:
        new_folder = doc.folder_id
        if body.parent_id is not None:
            parent = await repo.get(body.parent_id, user_id=user.user_id)
            if parent is None:
                raise HTTPException(status_code=404, detail="parent not found")
            if parent.kind != "folder":
                raise HTTPException(status_code=400, detail="parent is not a folder")
            new_folder = parent.folder_id
        await repo.move(
            document_id, user_id=user.user_id, parent_id=body.parent_id, folder_id=new_folder
        )
    refreshed = await repo.get(document_id, user_id=user.user_id)
    assert refreshed is not None  # just fetched under the same session
    return _detail(refreshed)


@router.delete("/{document_id}", response_model=DocumentWriteResult)
async def delete_document(
    document_id: str,
    user: AuthUser,
    repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentWriteResult:
    """Soft-delete a node and (for a folder) its whole subtree."""
    ok = await repo.soft_delete(document_id, user_id=user.user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentWriteResult(ok=True, version=memory_version(""))
