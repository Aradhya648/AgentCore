"""A1+ turn files diff — read-only baseline vs live workspace."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import AuthUser, get_conversation_repo, get_message_repo
from agentcore.api.schemas.turn_files_diff import TurnFileChange, TurnFilesDiffResponse
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import ConversationRepository, MessageRepository
from agentcore.storage.protocol import SnapshotNotFound
from agentcore.workspace.turn_diff import compute_turn_files_diff

from ._helpers import _get_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get(
    "/{conversation_id}/messages/{message_id}/files/diff",
    response_model=TurnFilesDiffResponse,
)
async def get_turn_files_diff(
    conversation_id: str,
    message_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    msg_repo: MessageRepository = Depends(get_message_repo),
) -> TurnFilesDiffResponse:
    """Compare the turn's baseline snapshot to the live cloud workspace (A1+).

    No baseline / snapshot missing → ``available=false`` (desktop falls back to A1
    tool-arg previews). Does not apply or restore anything.
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    msg = await msg_repo.get_by_id(message_id, conversation_id=conversation_id)
    if msg is None:
        raise NotFoundError("消息不存在")
    if msg.role != "assistant":
        raise NotFoundError("仅助手回合支持文件改动审阅")

    try:
        result = await compute_turn_files_diff(
            user_id=user.user_id,
            folder_id=conv.folder_id,
            conversation_id=conversation_id,
            message_id=message_id,
            baseline_snapshot_id=msg.baseline_snapshot_id,
        )
    except SnapshotNotFound:
        return TurnFilesDiffResponse(
            message_id=message_id,
            baseline_snapshot_id=msg.baseline_snapshot_id,
            available=False,
            data=[],
            total=0,
            added=0,
            modified=0,
            deleted=0,
        )

    rows = [
        TurnFileChange(
            path=c.path,
            change_type=c.change_type,  # type: ignore[arg-type]
            base_sha=c.base_sha,
            result_sha=c.result_sha,
            is_binary=c.is_binary,
            content=c.content,
            size_bytes=c.size_bytes,
            base_content=c.base_content,
        )
        for c in result.changes
    ]
    added = sum(1 for r in rows if r.change_type == "added")
    modified = sum(1 for r in rows if r.change_type == "modified")
    deleted = sum(1 for r in rows if r.change_type == "deleted")
    return TurnFilesDiffResponse(
        message_id=message_id,
        baseline_snapshot_id=result.baseline_snapshot_id,
        available=result.available,
        data=rows,
        total=len(rows),
        added=added,
        modified=modified,
        deleted=deleted,
    )
