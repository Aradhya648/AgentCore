"""Shared space REST schemas (多人共享空间, docs/02-架构/双模式工作区.md §十一)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SharedSpaceRole = Literal["owner", "editor", "viewer"]
SharedSpaceMemberState = Literal["accepted", "pending"]
SharedMountMode = Literal["readonly", "write"]


class CreateSharedSpaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class UpdateSharedSpaceRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)


class SharedSpaceSummary(BaseModel):
    id: str
    name: str
    owner_user_id: str
    my_role: SharedSpaceRole
    my_state: SharedSpaceMemberState
    member_count: int
    ws_id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SharedSpaceListResponse(BaseModel):
    data: list[SharedSpaceSummary]
    total: int


class InviteSharedSpaceMemberRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: Literal["editor", "viewer"] = "editor"


class UpdateSharedSpaceMemberRequest(BaseModel):
    role: Literal["editor", "viewer"]


class SharedSpaceMemberSummary(BaseModel):
    user_id: str
    role: SharedSpaceRole
    state: SharedSpaceMemberState
    invited_by: str | None = None
    joined_at: datetime | None = None
    display_name: str | None = None
    username: str | None = None


class SharedSpaceMemberListResponse(BaseModel):
    data: list[SharedSpaceMemberSummary]
    total: int


class SharedSpaceEventSummary(BaseModel):
    id: str
    space_id: str
    actor_user_id: str | None
    actor_via: Literal["user", "agent"]
    action: str
    path: str | None = None
    detail: dict | None = None
    created_at: datetime | None = None


class SharedSpaceEventListResponse(BaseModel):
    data: list[SharedSpaceEventSummary]
    total: int


class MountSharedSpaceRequest(BaseModel):
    """Mount a shared space into a cloud conversation as ``shared/<alias>/``."""

    space_id: str = Field(..., min_length=1)
    alias_hint: str | None = Field(None, max_length=64)


class SharedMountItem(BaseModel):
    alias: str
    space_id: str
    label: str
    namespace: str  # ``shared/<alias>``
    mode: SharedMountMode
    ws_id: str


class SharedMountListResponse(BaseModel):
    data: list[SharedMountItem]


class SharedMountResponse(BaseModel):
    mount: SharedMountItem
