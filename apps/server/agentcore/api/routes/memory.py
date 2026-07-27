"""Long-term AI memory routes — view / edit / clear + master switch (self-only).

The user's long-term memory is the markdown body of their `ai_maintained` rule file
(Agent记忆与知识系统 §1.4 / §五), today backed by the per-user ``MemoryStore`` on disk
until the cloud file tree lands. The desktop「AI 记忆」surface reads it here and edits
it through the SAME source-agnostic markdown editor the file workbench uses, so the
contract mirrors the workspace edit contract: full text + a CAS ``version`` baseline,
and a write reports a ``conflict`` (instead of clobbering) when the offline
consolidation — or another device — changed the file underneath.

All endpoints are self-only (``AuthUser``): memory is private per-user data. Writes
hold the per-user memory lock (``memory/locks.py``) so a manual save and the offline
consolidation pass can never interleave and lose each other's change.

Two editor surfaces sit on top, both reusing the workspace markdown editor (CAS contract):

- **Legacy combined doc** (``GET/PUT /users/me/memory``): treats the GLOBAL core as ONE
  document — combines 偏好.md + 画像.md on read (``merge_global_core``) and splits on write
  (``split_global_core``), which doubles as the organic 偏好/画像 migration (an old 画像.md
  still holding preference sections splits the first time it is saved). Still carries the
  master switch ``enabled``.
- **Per-leaf surface** (``GET/PUT /users/me/memory/files/{kind}``, P2): one editable leaf
  per (kind, scope) so the「文件」rail can show 偏好 / 画像 (global) and a project's 画像
  separately. ``preferences`` (偏好.md) is GLOBAL-only by invariant; ``profile`` (画像.md)
  honors an optional ``folder_id`` to address a project layer. ``GET …/projects`` lists the
  folder_ids that have project memory so the rail only surfaces a node where there is one.
- **On-demand topic surface** (``GET /users/me/memory/topics`` + ``GET/PUT …/topics/{slug}``):
  lists / reads / writes the ``主题/<slug>.md`` notes the agent pulls via ``consult_memory``,
  so the rail's 主题/ folder can finally browse·edit·delete them (Agent记忆与知识系统 §1.6).
  Same ``folder_id`` scope convention as the per-leaf surface (None = global); an empty PUT
  body deletes a note (mirrors clearing a leaf), which drops it from the 记忆主题目录.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agentcore.api.dependencies import (
    AuthUser,
    get_memory_store,
    get_memory_update_repo,
    get_user_repo,
)
from agentcore.api.schemas import MemoryUpdateItemView
from agentcore.db.repositories import MemoryUpdateRepository, UserRepository
from agentcore.memory import (
    CORE_MEMORY_FILE,
    PREFERENCES_MEMORY_FILE,
    DocumentMemoryStore,
    is_topic_path,
    memory_version,
    merge_global_core,
    split_global_core,
    topic_path,
    topic_slug,
)
from agentcore.memory.locks import user_memory_lock
from agentcore.memory.move_bullet import (
    MoveBulletConflict,
    MoveBulletError,
    MoveBulletOk,
    move_memory_bullet,
)

router = APIRouter(prefix="/users/me/memory", tags=["memory"])


class MemoryKind(StrEnum):
    """Which always-injected core leaf an editor surface addresses (Agent记忆与知识系统 §1.4).

    ``preferences`` → 偏好.md (沟通/工作习惯, GLOBAL-only); ``profile`` → 画像.md
    (技术栈/关于用户的事实, global or — with a ``folder_id`` — a project layer).
    """

    preferences = "preferences"
    profile = "profile"


def _resolve_file_scope(kind: MemoryKind, folder_id: str | None) -> tuple[str, str | None]:
    """Map a logical (kind, folder_id) to a concrete (file, scope).

    ``preferences`` is GLOBAL-only by invariant (§1.4 — preferences are universal, never
    copied into a project), so a ``folder_id`` is ignored. ``profile`` is global when
    ``folder_id`` is None, else that project's 画像.md.
    """
    if kind is MemoryKind.preferences:
        return PREFERENCES_MEMORY_FILE, None
    return CORE_MEMORY_FILE, folder_id


class MemoryResponse(BaseModel):
    """The user's memory document + the master switch (the editor's load payload)."""

    content: str
    # Content-addressed CAS tag (memory/store.py ``memory_version``); the client sends
    # it back as the write baseline so a stale overwrite is caught, not silently lost.
    version: str
    enabled: bool


class MemoryWriteRequest(BaseModel):
    content: str
    # The version the edit was based on. ``None`` writes unconditionally (used by
    # "清空记忆" / "仍然覆盖"); a non-null value that no longer matches → 200 conflict.
    baseline: str | None = None


class MemoryWriteResult(BaseModel):
    ok: bool
    version: str
    conflict: bool = False


class MemoryEnabledRequest(BaseModel):
    enabled: bool = Field(..., description="Long-term memory master switch")


class ConversationHistoryAccessResponse(BaseModel):
    """Cross-session conversation-log access gate (跨会话对话日志访问定案)."""

    enabled: bool


class ConversationHistoryAccessRequest(BaseModel):
    enabled: bool = Field(
        ..., description="Allow Workers to search/read past conversation transcripts"
    )


class MemoryFileResponse(BaseModel):
    """One memory leaf's body + its CAS tag (a single editor leaf's load payload)."""

    content: str
    version: str


class MemoryProjectsResponse(BaseModel):
    """folder_ids whose PROJECT memory layer is non-empty (the rail shows a node each)."""

    folders: list[str]


class MemoryTopicsResponse(BaseModel):
    """On-demand TOPIC note slugs in one scope (the rail's 主题/ folder listing).

    Names only (``主题/<slug>.md`` → ``slug``), sorted; the body is pulled per-note via
    ``GET …/topics/{slug}`` when the user opens one (渐进披露, mirrors ``consult_memory``).
    """

    topics: list[str]


class MemoryUpdateFeedItem(BaseModel):
    """One memory-write notice in the cross-conversation「记忆动态」feed.

    Same shape as the conversation-tail card (``kind`` / ``summary`` / ``items``), plus
    ``conversation_id`` so the feed can link back to the source conversation. Projected
    from a ``memory_updates`` row via ``from_attributes``.
    """

    id: str
    conversation_id: str
    kind: str = "semantic"
    summary: str | None = None
    items: list[MemoryUpdateItemView] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryUpdatesFeedResponse(BaseModel):
    """The user's recent memory updates across ALL conversations, NEWEST-first.

    Backs the「AI 记忆」editor's「最近更新」view (记忆编辑器的跨对话动态视图): the write side
    of memory is per-user long-term data, so its natural home is one chronological stream —
    a question the per-conversation tail card cannot answer.
    """

    updates: list[MemoryUpdateFeedItem]


class MemoryMoveBulletRequest(BaseModel):
    """Move one bullet between GLOBAL and the given project's layer (位置即作用域纠错).

    ``direction`` ``to_project`` = remove from global + add under the same section in
    ``folder_id``; ``to_global`` is the inverse. Optional CAS baselines mirror the
    per-leaf PUT contract (``None`` = unconditional under the memory lock).
    """

    content: str = Field(..., min_length=1, description="Bullet text to move")
    section: str = Field("", description="## section name (required for core leaves)")
    folder_id: str = Field(..., min_length=1, description="Current project folder id")
    direction: Literal["to_project", "to_global"]
    kind: Literal["preferences", "profile", "topic"] = "profile"
    topic_slug: str | None = None
    source_baseline: str | None = None
    target_baseline: str | None = None


class MemoryMoveBulletResult(BaseModel):
    ok: bool
    conflict: bool = False
    source_version: str = ""
    target_version: str = ""
    message: str | None = None


@router.get("", response_model=MemoryResponse)
async def get_my_memory(
    user: AuthUser, store: DocumentMemoryStore = Depends(get_memory_store)
) -> MemoryResponse:
    """Load the signed-in user's long-term memory + whether memory is enabled."""
    content = merge_global_core(
        await store.load(user.user_id, PREFERENCES_MEMORY_FILE),
        await store.load(user.user_id, CORE_MEMORY_FILE),
    )
    return MemoryResponse(
        content=content, version=memory_version(content), enabled=user.memory_enabled
    )


@router.put("", response_model=MemoryWriteResult)
async def put_my_memory(
    body: MemoryWriteRequest,
    user: AuthUser,
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryWriteResult:
    """Write the user's long-term memory back (full-document edit, CAS-guarded).

    Holds the per-user memory lock so the read-compare-write is atomic against the offline
    consolidation pass. A ``baseline`` that no longer matches the current (merged) version
    returns ``ok=False, conflict=True`` with the live version (never a blind overwrite); the
    client then reloads or forces the write with ``baseline=None``. The edited document is
    split back into 偏好.md + 画像.md; the returned version is that of the re-merged result so
    it matches what the next GET serves (split→save→merge normalizes the markdown).
    """
    async with user_memory_lock(user.user_id):
        current = merge_global_core(
            await store.load(user.user_id, PREFERENCES_MEMORY_FILE),
            await store.load(user.user_id, CORE_MEMORY_FILE),
        )
        current_version = memory_version(current)
        if body.baseline is not None and body.baseline != current_version:
            return MemoryWriteResult(ok=False, version=current_version, conflict=True)
        files = split_global_core(body.content)
        for file, markdown in files.items():
            if markdown:
                await store.save(user.user_id, file, markdown)
            else:
                # An empty file means that core file has no sections (e.g. all preferences
                # were removed, or "清空记忆"): drop it so it stops being injected.
                await store.delete(user.user_id, file)
        new_content = merge_global_core(
            files[PREFERENCES_MEMORY_FILE], files[CORE_MEMORY_FILE]
        )
    return MemoryWriteResult(ok=True, version=memory_version(new_content))


@router.put("/enabled", response_model=MemoryResponse)
async def set_my_memory_enabled(
    body: MemoryEnabledRequest,
    user: AuthUser,
    users: UserRepository = Depends(get_user_repo),
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryResponse:
    """Toggle the long-term memory master switch (off = stop injecting AND growing)."""
    await users.set_memory_enabled(user.user_id, body.enabled)
    content = merge_global_core(
        await store.load(user.user_id, PREFERENCES_MEMORY_FILE),
        await store.load(user.user_id, CORE_MEMORY_FILE),
    )
    return MemoryResponse(
        content=content, version=memory_version(content), enabled=body.enabled
    )


@router.get(
    "/conversation-history-access",
    response_model=ConversationHistoryAccessResponse,
)
async def get_my_conversation_history_access(
    user: AuthUser,
) -> ConversationHistoryAccessResponse:
    """Whether Workers may search/read this account's past conversation logs."""
    return ConversationHistoryAccessResponse(enabled=user.conversation_history_access)


@router.put(
    "/conversation-history-access",
    response_model=ConversationHistoryAccessResponse,
)
async def set_my_conversation_history_access(
    body: ConversationHistoryAccessRequest,
    user: AuthUser,
    users: UserRepository = Depends(get_user_repo),
) -> ConversationHistoryAccessResponse:
    """Toggle cross-session conversation-log access (orthogonal to memory_enabled)."""
    await users.set_conversation_history_access(user.user_id, body.enabled)
    return ConversationHistoryAccessResponse(enabled=body.enabled)


@router.get("/projects", response_model=MemoryProjectsResponse)
async def list_my_memory_projects(
    user: AuthUser, store: DocumentMemoryStore = Depends(get_memory_store)
) -> MemoryProjectsResponse:
    """List folder_ids that have project-scoped memory (so the「文件」rail can surface them).

    Declared before ``/files/{kind}`` so the static segment wins the route match.
    """
    return MemoryProjectsResponse(folders=await store.project_scopes(user.user_id))


@router.post("/move-bullet", response_model=MemoryMoveBulletResult)
async def move_my_memory_bullet(
    body: MemoryMoveBulletRequest,
    user: AuthUser,
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryMoveBulletResult:
    """Move one memory bullet between global and the current project (P2-b 搬层纠错).

    Declared before ``/files/{kind}`` so the static segment wins the route match.
    Holds the per-user memory lock; illegal sections (偏好 / 纠正记录 → project,
    项目约束 → global) return 422 with a clear message.
    """
    async with user_memory_lock(user.user_id):
        result = await move_memory_bullet(
            store,
            user_id=user.user_id,
            content=body.content,
            section=body.section,
            folder_id=body.folder_id,
            direction=body.direction,
            kind=body.kind,
            topic_slug=body.topic_slug,
            source_baseline=body.source_baseline,
            target_baseline=body.target_baseline,
        )
    if isinstance(result, MoveBulletError):
        raise HTTPException(
            status_code=422,
            detail={"code": "memory_move_rejected", "message": result.message},
        )
    if isinstance(result, MoveBulletConflict):
        return MemoryMoveBulletResult(
            ok=False,
            conflict=True,
            source_version=result.source_version,
            target_version=result.target_version,
        )
    assert isinstance(result, MoveBulletOk)
    return MemoryMoveBulletResult(
        ok=True,
        source_version=result.source_version,
        target_version=result.target_version,
    )


@router.get("/updates", response_model=MemoryUpdatesFeedResponse)
async def list_my_memory_updates(
    user: AuthUser,
    mem_update_repo: MemoryUpdateRepository = Depends(get_memory_update_repo),
    limit: int = 50,
) -> MemoryUpdatesFeedResponse:
    """The signed-in user's recent memory updates across ALL conversations (记忆动态 feed).

    Newest-first; the offline consolidation pass appends a row whenever it changed a memory
    file, so this is the「AI 最近学了什么」stream that powers the editor's「最近更新」view.
    Declared before ``/files/{kind}`` / ``/topics/{slug}`` so the static segment wins the
    route match.
    """
    rows = await mem_update_repo.list_for_user(user.user_id, limit=limit)
    return MemoryUpdatesFeedResponse(
        updates=[MemoryUpdateFeedItem.model_validate(row) for row in rows]
    )


@router.get("/topics", response_model=MemoryTopicsResponse)
async def list_my_memory_topics(
    user: AuthUser,
    folder_id: str | None = None,
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryTopicsResponse:
    """List on-demand TOPIC note slugs in one scope (the rail's 主题/ folder listing).

    ``folder_id`` None = the GLOBAL 主题/ folder; a folder_id = that project's. Same scope
    convention as ``/files/{kind}`` (no separate ``scope`` enum). Declared before
    ``/topics/{slug}`` / ``/files/{kind}`` so the static segment wins the route match.
    """
    metas = await store.list(user.user_id, scope=folder_id)
    return MemoryTopicsResponse(
        topics=sorted(topic_slug(m.path) for m in metas if is_topic_path(m.path))
    )


@router.get("/topics/{slug}", response_model=MemoryFileResponse)
async def get_my_memory_topic(
    slug: str,
    user: AuthUser,
    folder_id: str | None = None,
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryFileResponse:
    """Load ONE on-demand TOPIC note's body — global (``folder_id`` None) or a project's."""
    content = await store.load(user.user_id, topic_path(slug), scope=folder_id)
    return MemoryFileResponse(content=content, version=memory_version(content))


@router.put("/topics/{slug}", response_model=MemoryWriteResult)
async def put_my_memory_topic(
    slug: str,
    body: MemoryWriteRequest,
    user: AuthUser,
    folder_id: str | None = None,
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryWriteResult:
    """Write ONE TOPIC note back (CAS-guarded; an empty body deletes — mirrors ``/files/{kind}``).

    Holds the per-user memory lock so the read-compare-write is atomic against the offline
    consolidation pass. A ``baseline`` that no longer matches the note's current version
    returns ``ok=False, conflict=True`` (never a blind overwrite). Clearing a note (empty
    content) deletes the underlying file so it leaves the 记忆主题目录 (and stops being
    consult-able).
    """
    async with user_memory_lock(user.user_id):
        current = await store.load(user.user_id, topic_path(slug), scope=folder_id)
        current_version = memory_version(current)
        if body.baseline is not None and body.baseline != current_version:
            return MemoryWriteResult(ok=False, version=current_version, conflict=True)
        if body.content:
            await store.save(user.user_id, topic_path(slug), body.content, scope=folder_id)
        else:
            await store.delete(user.user_id, topic_path(slug), scope=folder_id)
    return MemoryWriteResult(ok=True, version=memory_version(body.content))


@router.get("/files/{kind}", response_model=MemoryFileResponse)
async def get_my_memory_file(
    kind: MemoryKind,
    user: AuthUser,
    folder_id: str | None = None,
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryFileResponse:
    """Load ONE memory leaf — 偏好/画像 (global) or a project's 画像 (with ``folder_id``)."""
    file, scope = _resolve_file_scope(kind, folder_id)
    content = await store.load(user.user_id, file, scope=scope)
    return MemoryFileResponse(content=content, version=memory_version(content))


@router.put("/files/{kind}", response_model=MemoryWriteResult)
async def put_my_memory_file(
    kind: MemoryKind,
    body: MemoryWriteRequest,
    user: AuthUser,
    folder_id: str | None = None,
    store: DocumentMemoryStore = Depends(get_memory_store),
) -> MemoryWriteResult:
    """Write ONE memory leaf back (CAS-guarded; an empty body drops the file).

    Holds the per-user memory lock so the read-compare-write is atomic against the offline
    consolidation pass. A ``baseline`` that no longer matches the leaf's current version
    returns ``ok=False, conflict=True`` (never a blind overwrite). Clearing a leaf (empty
    content) deletes the underlying file so it stops being injected.
    """
    file, scope = _resolve_file_scope(kind, folder_id)
    async with user_memory_lock(user.user_id):
        current = await store.load(user.user_id, file, scope=scope)
        current_version = memory_version(current)
        if body.baseline is not None and body.baseline != current_version:
            return MemoryWriteResult(ok=False, version=current_version, conflict=True)
        if body.content:
            await store.save(user.user_id, file, body.content, scope=scope)
        else:
            await store.delete(user.user_id, file, scope=scope)
    return MemoryWriteResult(ok=True, version=memory_version(body.content))
