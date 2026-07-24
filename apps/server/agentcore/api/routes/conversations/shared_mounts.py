"""Session-scoped shared-space mounts on cloud conversations (D2)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_db,
    get_shared_space_service,
)
from agentcore.api.schemas import StatusResponse
from agentcore.api.schemas.shared_spaces import (
    MountSharedSpaceRequest,
    SharedMountItem,
    SharedMountListResponse,
    SharedMountResponse,
)
from agentcore.conversation.common import resolve_local_binding
from agentcore.core.errors import ConflictError, NotFoundError
from agentcore.db.repositories import ConversationRepository
from agentcore.shared_spaces.service import SharedSpaceService
from agentcore.shared_spaces.types import role_to_mount_mode
from agentcore.workspace import shared_mount_store
from agentcore.workspace.locate import format_shared_workspace_id
from agentcore.workspace.shared_mounts import shared_ns

from ._helpers import _get_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _item(m) -> SharedMountItem:
    return SharedMountItem(
        alias=m.alias,
        space_id=m.space_id,
        label=m.label,
        namespace=shared_ns(m.alias),
        mode=m.mode,
        ws_id=format_shared_workspace_id(m.space_id),
    )


@router.get(
    "/{conversation_id}/workspace/shared-mounts",
    response_model=SharedMountListResponse,
)
async def list_shared_mounts(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    return SharedMountListResponse(
        data=[_item(m) for m in shared_mount_store.list_mounts(conversation_id)]
    )


@router.post(
    "/{conversation_id}/workspace/shared-mounts",
    response_model=SharedMountResponse,
    status_code=201,
)
async def mount_shared_space(
    conversation_id: str,
    body: MountSharedSpaceRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    service: SharedSpaceService = Depends(get_shared_space_service),
    session: AsyncSession = Depends(get_db),
):
    """Mount a shared space into a **cloud** conversation (D2).

    Local-bound conversations (sidecar) cannot mount — no cross-runtime dual root.
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    if await resolve_local_binding(session, conv) is not None:
        raise ConflictError("本地执行的对话不能挂载共享空间")
    access = await service.resolve_mount_access(
        space_id=body.space_id, user_id=user.user_id
    )
    if access is None:
        raise NotFoundError("共享空间不存在")
    space = await service.get_space(space_id=body.space_id, user_id=user.user_id)
    mount = shared_mount_store.add_mount(
        conversation_id,
        space_id=body.space_id,
        label=space.name,
        mode=role_to_mount_mode(access.role),
        alias_hint=body.alias_hint or space.name,
    )
    return SharedMountResponse(mount=_item(mount))


@router.delete(
    "/{conversation_id}/workspace/shared-mounts",
    response_model=StatusResponse,
)
async def revoke_shared_mounts(
    conversation_id: str,
    user: AuthUser,
    alias: str | None = Query(None),
    space_id: str | None = Query(None),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    if alias is None and space_id is None:
        shared_mount_store.clear_conversation(conversation_id)
        return StatusResponse()
    ok = shared_mount_store.revoke_mount(
        conversation_id, alias=alias, space_id=space_id
    )
    if not ok:
        raise NotFoundError("挂载不存在或已撤销")
    return StatusResponse()
