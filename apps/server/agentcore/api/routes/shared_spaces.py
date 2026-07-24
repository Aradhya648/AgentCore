"""Shared space REST routes (``/v1/shared-spaces``)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from agentcore.api.dependencies import AuthUser, get_shared_space_service
from agentcore.api.schemas import StatusResponse
from agentcore.api.schemas.shared_spaces import (
    CreateSharedSpaceRequest,
    InviteSharedSpaceMemberRequest,
    SharedSpaceEventListResponse,
    SharedSpaceEventSummary,
    SharedSpaceListResponse,
    SharedSpaceMemberListResponse,
    SharedSpaceMemberSummary,
    SharedSpaceSummary,
    UpdateSharedSpaceMemberRequest,
    UpdateSharedSpaceRequest,
)
from agentcore.shared_spaces.service import SharedSpaceService
from agentcore.workspace.locate import format_shared_workspace_id

router = APIRouter(prefix="/shared-spaces", tags=["shared-spaces"])


def _space_summary(view) -> SharedSpaceSummary:
    return SharedSpaceSummary(
        id=view.id,
        name=view.name,
        owner_user_id=view.owner_user_id,
        my_role=view.my_role,
        my_state=view.my_state,
        member_count=view.member_count,
        ws_id=format_shared_workspace_id(view.id),
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _member_summary(view) -> SharedSpaceMemberSummary:
    return SharedSpaceMemberSummary(
        user_id=view.user_id,
        role=view.role,
        state=view.state,
        invited_by=view.invited_by,
        joined_at=view.joined_at,
        display_name=view.display_name,
        username=view.username,
    )


@router.post("", response_model=SharedSpaceSummary, status_code=201)
async def create_shared_space(
    body: CreateSharedSpaceRequest,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    view = await service.create_space(owner_id=user.user_id, name=body.name)
    return _space_summary(view)


@router.get("", response_model=SharedSpaceListResponse)
async def list_shared_spaces(
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    views = await service.list_spaces(user_id=user.user_id)
    return SharedSpaceListResponse(
        data=[_space_summary(v) for v in views], total=len(views)
    )


@router.get("/invites/pending", response_model=SharedSpaceListResponse)
async def list_pending_invites(
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    views = await service.list_pending_invites(user_id=user.user_id)
    return SharedSpaceListResponse(
        data=[_space_summary(v) for v in views], total=len(views)
    )


@router.get("/{space_id}", response_model=SharedSpaceSummary)
async def get_shared_space(
    space_id: str,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    view = await service.get_space(space_id=space_id, user_id=user.user_id)
    return _space_summary(view)


@router.patch("/{space_id}", response_model=SharedSpaceSummary)
async def update_shared_space(
    space_id: str,
    body: UpdateSharedSpaceRequest,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    if body.name is None:
        view = await service.get_space(space_id=space_id, user_id=user.user_id)
        return _space_summary(view)
    view = await service.rename_space(
        space_id=space_id, user_id=user.user_id, name=body.name
    )
    return _space_summary(view)


@router.delete("/{space_id}", response_model=StatusResponse)
async def delete_shared_space(
    space_id: str,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    await service.delete_space(space_id=space_id, user_id=user.user_id)
    return StatusResponse()


@router.post("/{space_id}/invites", response_model=SharedSpaceMemberSummary, status_code=201)
async def invite_member(
    space_id: str,
    body: InviteSharedSpaceMemberRequest,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    view = await service.invite(
        space_id=space_id,
        actor_id=user.user_id,
        target_user_id=body.user_id,
        role=body.role,
    )
    return _member_summary(view)


@router.post("/{space_id}/invites/accept", response_model=SharedSpaceSummary)
async def accept_invite(
    space_id: str,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    view = await service.accept_invite(space_id=space_id, user_id=user.user_id)
    return _space_summary(view)


@router.post("/{space_id}/invites/reject", response_model=StatusResponse)
async def reject_invite(
    space_id: str,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    await service.reject_invite(space_id=space_id, user_id=user.user_id)
    return StatusResponse()


@router.get("/{space_id}/members", response_model=SharedSpaceMemberListResponse)
async def list_members(
    space_id: str,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    views = await service.list_members(space_id=space_id, user_id=user.user_id)
    return SharedSpaceMemberListResponse(
        data=[_member_summary(v) for v in views], total=len(views)
    )


@router.patch(
    "/{space_id}/members/{member_user_id}",
    response_model=SharedSpaceMemberSummary,
)
async def change_member_role(
    space_id: str,
    member_user_id: str,
    body: UpdateSharedSpaceMemberRequest,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    view = await service.change_role(
        space_id=space_id,
        actor_id=user.user_id,
        target_user_id=member_user_id,
        role=body.role,
    )
    return _member_summary(view)


@router.delete("/{space_id}/members/{member_user_id}", response_model=StatusResponse)
async def remove_or_leave_member(
    space_id: str,
    member_user_id: str,
    user: AuthUser,
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    """Owner removes ``member_user_id``, or a member leaves when targeting self."""
    if member_user_id == user.user_id:
        await service.leave(space_id=space_id, user_id=user.user_id)
    else:
        await service.remove_member(
            space_id=space_id, actor_id=user.user_id, target_user_id=member_user_id
        )
    return StatusResponse()


@router.get("/{space_id}/events", response_model=SharedSpaceEventListResponse)
async def list_events(
    space_id: str,
    user: AuthUser,
    limit: int = Query(50, ge=1, le=200),
    before_id: str | None = Query(None),
    service: SharedSpaceService = Depends(get_shared_space_service),
):
    events = await service.list_events(
        space_id=space_id, user_id=user.user_id, limit=limit, before_id=before_id
    )
    data = [
        SharedSpaceEventSummary(
            id=e.id,
            space_id=e.space_id,
            actor_user_id=e.actor_user_id,
            actor_via=e.actor_via,  # type: ignore[arg-type]
            action=e.action,
            path=e.path,
            detail=e.detail,
            created_at=e.created_at,
        )
        for e in events
    ]
    return SharedSpaceEventListResponse(data=data, total=len(data))
