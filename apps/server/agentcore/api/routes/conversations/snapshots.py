"""Workspace snapshots (axis-3 persistence: backup / kept versions / download)."""

from fastapi import APIRouter, Depends, Response

from agentcore.api.dependencies import AuthUser, get_conversation_repo
from agentcore.api.schemas import (
    CreateSnapshotRequest,
    SnapshotListResponse,
    SnapshotSummary,
    StatusResponse,
)
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import ConversationRepository
from agentcore.storage import SnapshotNotFound
from agentcore.workspace.locate import workspace_storage_key
from agentcore.workspace.locks import workspace_lock
from agentcore.workspace.snapshots import (
    create_snapshot,
    list_snapshots,
    read_snapshot,
    restore_snapshot,
)

from ._helpers import _get_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/{conversation_id}/snapshots", response_model=SnapshotListResponse)
async def list_conversation_snapshots(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """List the conversation's workspace snapshots (newest first)."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    refs = await list_snapshots(
        user_id=user.user_id,
        folder_id=conv.folder_id,
        conversation_id=conversation_id,
    )
    return SnapshotListResponse(
        data=[SnapshotSummary.model_validate(r) for r in refs],
        total=len(refs),
    )


@router.post("/{conversation_id}/snapshots", response_model=SnapshotSummary, status_code=201)
async def create_conversation_snapshot(
    conversation_id: str,
    body: CreateSnapshotRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Take a manual snapshot of the workspace (a ``label`` keeps it as a version)."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    key = workspace_storage_key(
        user_id=user.user_id, folder_id=conv.folder_id, conversation_id=conversation_id
    )
    # Folder lock (决策④): serialize the manifest write against a running turn's
    # auto-snapshot and other same-workspace mutations.
    async with workspace_lock(key):
        ref = await create_snapshot(
            user_id=user.user_id,
            folder_id=conv.folder_id,
            conversation_id=conversation_id,
            label=body.label,
        )
    return SnapshotSummary.model_validate(ref)


@router.post("/{conversation_id}/snapshots/{snapshot_id}/restore", response_model=StatusResponse)
async def restore_conversation_snapshot(
    conversation_id: str,
    snapshot_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Restore the workspace to a snapshot (overwrites current files)."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    key = workspace_storage_key(
        user_id=user.user_id, folder_id=conv.folder_id, conversation_id=conversation_id
    )
    # Folder lock (决策④): a restore rewrites the whole workspace, so it must not
    # interleave with a running turn or another mutation on the same space.
    try:
        async with workspace_lock(key):
            await restore_snapshot(
                user_id=user.user_id,
                folder_id=conv.folder_id,
                conversation_id=conversation_id,
                snapshot_id=snapshot_id,
            )
    except SnapshotNotFound as e:
        raise NotFoundError("快照不存在") from e
    return StatusResponse()


@router.get("/{conversation_id}/snapshots/{snapshot_id}/download")
async def download_conversation_snapshot(
    conversation_id: str,
    snapshot_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Download a snapshot archive (zip) of the workspace at that point in time."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    try:
        data = await read_snapshot(
            user_id=user.user_id,
            folder_id=conv.folder_id,
            conversation_id=conversation_id,
            snapshot_id=snapshot_id,
        )
    except SnapshotNotFound as e:
        raise NotFoundError("快照不存在") from e
    filename = f"workspace-{snapshot_id}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
