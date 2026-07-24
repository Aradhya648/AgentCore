"""Folder CRUD routes (项目 = 工作区).

Folders are user-scoped: every route resolves the authenticated user and a
non-owner receives 404 (IDOR-safe). Soft-deleting a folder archives its
conversations in place (keeps ``folder_id``); workspace binding is set at
create and is immutable thereafter.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_db, get_folder_repo
from agentcore.api.schemas import (
    CollaborationDossierRef,
    CollaborationTimelineAct,
    CollaborationTimelineItem,
    CollaborationTimelineResponse,
    CreateFolderRequest,
    FolderSummary,
    StatusResponse,
    UpdateFolderRequest,
)
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import FolderRepository
from agentcore.folders.collaboration_timeline import (
    display_act_title,
    list_folder_collaboration_timeline,
)
from agentcore.folders.permanent_delete import permanent_delete_folder

router = APIRouter(prefix="/folders", tags=["folders"])


@router.post("", response_model=FolderSummary, status_code=201)
async def create_folder(
    body: CreateFolderRequest,
    user: AuthUser,
    repo: FolderRepository = Depends(get_folder_repo),
):
    folder = await repo.create(
        user_id=user.user_id,
        name=body.name,
        local_root_id=body.local_root_id if body.mode == "local" else None,
        local_subpath=body.local_subpath if body.mode == "local" else None,
    )
    return FolderSummary.from_folder(folder)


@router.get("", response_model=list[FolderSummary])
async def list_folders(
    user: AuthUser,
    repo: FolderRepository = Depends(get_folder_repo),
):
    folders = await repo.list_by_user(user.user_id)
    return [FolderSummary.from_folder(f) for f in folders]


@router.patch("/{folder_id}", response_model=FolderSummary)
async def update_folder(
    folder_id: str,
    body: UpdateFolderRequest,
    user: AuthUser,
    repo: FolderRepository = Depends(get_folder_repo),
):
    fields = body.model_fields_set
    kwargs: dict = {}
    if "name" in fields:
        kwargs["name"] = body.name
    folder = await repo.update(folder_id, user_id=user.user_id, **kwargs)
    if not folder:
        raise NotFoundError("文件夹不存在")
    return FolderSummary.from_folder(folder)


@router.delete("/{folder_id}", response_model=StatusResponse)
async def delete_folder(
    folder_id: str,
    user: AuthUser,
    repo: FolderRepository = Depends(get_folder_repo),
):
    deleted = await repo.soft_delete(folder_id, user_id=user.user_id)
    if not deleted:
        raise NotFoundError("文件夹不存在")
    return StatusResponse()


@router.delete("/{folder_id}/permanent", response_model=StatusResponse)
async def delete_folder_permanent(
    folder_id: str,
    user: AuthUser,
):
    """彻底删除项目：清盘成员对话 + 云端共享工作区/快照，再移除项目行.

    Distinct from ``DELETE /{folder_id}`` (soft-delete + archive members).
    Local-mode OS directories are never touched — only DB + server-side data.
    """
    deleted = await permanent_delete_folder(folder_id=folder_id, user_id=user.user_id)
    if not deleted:
        raise NotFoundError("文件夹不存在")
    return StatusResponse()


@router.get(
    "/{folder_id}/collaboration-timeline",
    response_model=CollaborationTimelineResponse,
)
async def get_collaboration_timeline(
    folder_id: str,
    user: AuthUser,
    repo: FolderRepository = Depends(get_folder_repo),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
):
    """项目协作时间线（读时聚合）：有 execution 的会话 + 幕序列摘要 + 案卷引用条.

    零写路径。案卷快照（research/ / debate/ 文件列表）复用工作区文件 API，不在此返回。
    """
    folder = await repo.get_by_id(folder_id, user_id=user.user_id)
    if not folder:
        raise NotFoundError("文件夹不存在")
    result = await list_folder_collaboration_timeline(
        session,
        folder_id=folder_id,
        user_id=user.user_id,
        limit=limit,
        offset=offset,
    )
    items = [
        CollaborationTimelineItem(
            conversation_id=it.conversation_id,
            title=it.title,
            updated_at=it.updated_at,
            execution_id=it.execution_id,
            host_turn_id=it.host_turn_id,
            acts=[
                CollaborationTimelineAct(
                    act_id=a.act_id,
                    kind=a.kind if a.kind in ("multi_agent", "debate") else "multi_agent",
                    title=display_act_title(kind=a.kind, title=a.title),
                    started_at=a.started_at,
                )
                for a in it.acts
            ],
            dossier_refs=[
                CollaborationDossierRef(path=r.path, sources=list(r.sources))
                for r in it.dossier_refs
            ],
        )
        for it in result.items
    ]
    return CollaborationTimelineResponse(
        folder_id=result.folder_id,
        items=items,
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        dossier_refs_note=result.dossier_refs_note,
    )
