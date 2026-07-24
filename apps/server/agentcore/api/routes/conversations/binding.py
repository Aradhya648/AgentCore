"""Local-mode binding (双模式工作区 §七: 模式跟着文件在哪自动走)."""

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_folder_repo,
)
from agentcore.api.schemas import BindLocalWorkspaceRequest, WorkspaceBindingResponse
from agentcore.core.errors import ConflictError, NotFoundError
from agentcore.db.models import Conversation
from agentcore.db.repositories import ConversationRepository, FolderRepository

from ._helpers import _get_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _binding_response(
    conv: Conversation,
    *,
    folder_repo: FolderRepository,
) -> WorkspaceBindingResponse:
    """Render effective workspace mode using the same口径 as turn routing."""
    if conv.folder_id:
        folder = await folder_repo.get_by_id_unscoped(conv.folder_id)
        if folder and folder.local_root_id:
            return WorkspaceBindingResponse(
                mode="local",
                scope="folder",
                root_id=folder.local_root_id,
                source="explicit",
            )
        return WorkspaceBindingResponse(
            mode="cloud", scope="folder", root_id=None, source=None
        )
    if conv.local_root_id:
        return WorkspaceBindingResponse(
            mode="local",
            scope="conversation",
            root_id=conv.local_root_id,
            source="explicit",
        )
    if conv.local_container_root_id:
        return WorkspaceBindingResponse(
            mode="local",
            scope="conversation",
            root_id=conv.local_container_root_id,
            source="container",
        )
    return WorkspaceBindingResponse(
        mode="cloud", scope="conversation", root_id=None, source=None
    )


def _reject_project_rebind(conv: Conversation) -> None:
    if conv.folder_id is not None:
        raise ConflictError("项目工作区创建后不可改；请在裸聊上绑定本地目录")


@router.get("/{conversation_id}/workspace/binding", response_model=WorkspaceBindingResponse)
async def get_workspace_binding(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
):
    """Report a conversation's resolved workspace mode (local vs cloud)."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    return await _binding_response(conv, folder_repo=folder_repo)


@router.put("/{conversation_id}/workspace/binding", response_model=WorkspaceBindingResponse)
async def bind_workspace(
    conversation_id: str,
    body: BindLocalWorkspaceRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
):
    """Bind a 裸聊's scratch workspace to a desktop FS root (switch to local).

    Project conversations inherit an immutable project binding — returns 409.
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    _reject_project_rebind(conv)
    await conv_repo.set_local_binding(conversation_id, root_id=body.root_id, subpath=None)
    conv = await conv_repo.get_by_id(conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    return await _binding_response(conv, folder_repo=folder_repo)


@router.delete("/{conversation_id}/workspace/binding", response_model=WorkspaceBindingResponse)
async def unbind_workspace(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    folder_repo: FolderRepository = Depends(get_folder_repo),
):
    """Unbind a 裸聊's scratch workspace (fall back to cloud). Project chats → 409."""
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    _reject_project_rebind(conv)
    await conv_repo.set_local_binding(conversation_id, root_id=None, subpath=None)
    conv = await conv_repo.get_by_id(conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    return await _binding_response(conv, folder_repo=folder_repo)
