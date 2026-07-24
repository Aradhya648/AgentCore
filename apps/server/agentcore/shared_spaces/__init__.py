"""Shared spaces domain (多人共享空间, docs/02-架构/双模式工作区.md §十一)."""

from agentcore.shared_spaces.service import MountAccess, SharedSpaceService
from agentcore.shared_spaces.types import (
    MemberView,
    SharedMountMode,
    SharedSpaceRole,
    SpaceView,
    can_write,
    role_to_mount_mode,
)

__all__ = [
    "MemberView",
    "MountAccess",
    "SharedMountMode",
    "SharedSpaceRole",
    "SharedSpaceService",
    "SpaceView",
    "can_write",
    "role_to_mount_mode",
]
