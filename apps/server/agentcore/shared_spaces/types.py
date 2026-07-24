"""Shared-space domain types and role helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SharedSpaceRole = Literal["owner", "editor", "viewer"]
SharedSpaceMemberState = Literal["accepted", "pending"]
SharedMountMode = Literal["readonly", "write"]
ActorVia = Literal["user", "agent"]

WRITABLE_ROLES: frozenset[SharedSpaceRole] = frozenset({"owner", "editor"})


def role_to_mount_mode(role: SharedSpaceRole) -> SharedMountMode:
    """Map member role → session mount capability (D2)."""
    return "write" if role in WRITABLE_ROLES else "readonly"


def can_write(role: SharedSpaceRole) -> bool:
    return role in WRITABLE_ROLES


@dataclass(frozen=True)
class SpaceView:
    """One space as seen by a member (list / detail)."""

    id: str
    name: str
    owner_user_id: str
    my_role: SharedSpaceRole
    my_state: SharedSpaceMemberState
    member_count: int
    created_at: object | None = None
    updated_at: object | None = None


@dataclass(frozen=True)
class MemberView:
    user_id: str
    role: SharedSpaceRole
    state: SharedSpaceMemberState
    invited_by: str | None
    joined_at: object | None
    display_name: str | None = None
    username: str | None = None
