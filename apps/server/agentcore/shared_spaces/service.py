"""SharedSpaceService — member lifecycle, invites, quotas, firehose + events."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agentcore.core.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    QuotaExceededError,
    RateLimitedError,
    ValidationError,
)
from agentcore.core.logging import get_logger
from agentcore.db.models.shared_spaces import SharedSpace, SharedSpaceEvent, SharedSpaceMember
from agentcore.db.models.users import User
from agentcore.db.repositories.shared_spaces import SharedSpaceRepository
from agentcore.db.repositories.users import (
    UserBlockRepository,
    UserDirectoryRepository,
    UserRepository,
)
from agentcore.messaging.events import ChatEventPublisher, NullChatEventPublisher
from agentcore.middleware.rate_limit import FixedWindowRateLimiter
from agentcore.shared_spaces.limits import (
    DEFAULT_INVITE_RATE_MAX,
    DEFAULT_INVITE_RATE_WINDOW_SECONDS,
    DEFAULT_MAX_MEMBERS_PER_SPACE,
    DEFAULT_MAX_SPACE_BYTES,
    DEFAULT_MAX_SPACES_PER_OWNER,
)
from agentcore.shared_spaces.types import (
    MemberView,
    SharedMountMode,
    SharedSpaceRole,
    SpaceView,
    can_write,
    role_to_mount_mode,
)
from agentcore.workspace import shared_mount_store
from agentcore.workspace.shared_paths import (
    shared_workspace_root_path,
    shared_workspace_storage_key,
)

logger = get_logger(__name__)

_INVITE_ROLES: frozenset[str] = frozenset({"editor", "viewer"})


@dataclass(frozen=True)
class MountAccess:
    """Realtime mount capability for a (user, space) pair."""

    mode: SharedMountMode
    role: SharedSpaceRole


class SharedSpaceService:
    """File-only shared space domain (提案 D1–D4)."""

    def __init__(
        self,
        *,
        spaces: SharedSpaceRepository,
        users: UserRepository,
        blocks: UserBlockRepository,
        directory: UserDirectoryRepository,
        events: ChatEventPublisher | None = None,
        max_spaces_per_owner: int = DEFAULT_MAX_SPACES_PER_OWNER,
        max_members_per_space: int = DEFAULT_MAX_MEMBERS_PER_SPACE,
        max_space_bytes: int = DEFAULT_MAX_SPACE_BYTES,
        invite_rate_max: int = DEFAULT_INVITE_RATE_MAX,
        invite_rate_window_seconds: int = DEFAULT_INVITE_RATE_WINDOW_SECONDS,
        invite_limiter: FixedWindowRateLimiter | None = None,
    ) -> None:
        self._spaces = spaces
        self._users = users
        self._blocks = blocks
        self._directory = directory
        self._events: ChatEventPublisher = events or NullChatEventPublisher()
        self._max_spaces = max_spaces_per_owner
        self._max_members = max_members_per_space
        self._max_bytes = max_space_bytes
        self._invite_limiter = invite_limiter or FixedWindowRateLimiter(
            max_requests=invite_rate_max,
            window_seconds=invite_rate_window_seconds,
        )

    # --- CRUD ---

    async def create_space(self, *, owner_id: str, name: str) -> SpaceView:
        name = name.strip()
        if not name:
            raise ValidationError("名称不能为空")
        owned = await self._spaces.count_owned_spaces(owner_id)
        if owned >= self._max_spaces:
            raise QuotaExceededError(
                f"共享空间数量已达上限（{self._max_spaces}）",
                dimension="shared_spaces",
            )
        space = await self._spaces.create_space(owner_user_id=owner_id, name=name)
        # Materialize disk root eagerly so file-hub listing is consistent.
        shared_workspace_root_path(space.id).mkdir(parents=True, exist_ok=True)
        await self._record_and_fanout(
            space_id=space.id,
            actor_user_id=owner_id,
            actor_via="user",
            action="space_created",
            detail={"name": name},
        )
        return SpaceView(
            id=space.id,
            name=space.name,
            owner_user_id=space.owner_user_id,
            my_role="owner",
            my_state="accepted",
            member_count=1,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )

    async def list_spaces(self, *, user_id: str) -> list[SpaceView]:
        rows = await self._spaces.list_spaces_for_user(user_id, state="accepted")
        views: list[SpaceView] = []
        for space, member in rows:
            count = await self._spaces.count_members(space.id)
            views.append(
                SpaceView(
                    id=space.id,
                    name=space.name,
                    owner_user_id=space.owner_user_id,
                    my_role=member.role,  # type: ignore[arg-type]
                    my_state=member.state,  # type: ignore[arg-type]
                    member_count=count,
                    created_at=space.created_at,
                    updated_at=space.updated_at,
                )
            )
        return views

    async def get_space(self, *, space_id: str, user_id: str) -> SpaceView:
        space, member = await self._require_accepted_member(space_id, user_id)
        count = await self._spaces.count_members(space.id)
        return SpaceView(
            id=space.id,
            name=space.name,
            owner_user_id=space.owner_user_id,
            my_role=member.role,  # type: ignore[arg-type]
            my_state=member.state,  # type: ignore[arg-type]
            member_count=count,
            created_at=space.created_at,
            updated_at=space.updated_at,
        )

    async def rename_space(self, *, space_id: str, user_id: str, name: str) -> SpaceView:
        name = name.strip()
        if not name:
            raise ValidationError("名称不能为空")
        space, member = await self._require_accepted_member(space_id, user_id)
        if member.role != "owner":
            raise AuthorizationError("仅所有者可重命名共享空间")
        updated = await self._spaces.update_space(space_id, name=name)
        assert updated is not None
        await self._record_and_fanout(
            space_id=space_id,
            actor_user_id=user_id,
            actor_via="user",
            action="space_renamed",
            detail={"name": name},
        )
        return await self.get_space(space_id=space_id, user_id=user_id)

    async def delete_space(self, *, space_id: str, user_id: str) -> None:
        space, member = await self._require_accepted_member(space_id, user_id)
        if member.role != "owner":
            raise AuthorizationError("仅所有者可删除共享空间")
        member_ids = [m.user_id for m in await self._spaces.list_members(space_id)]
        await self._spaces.delete_space(space_id)
        shared_mount_store.revoke_space_everywhere(space_id)
        self._rm_disk(space_id)
        await self._events.publish(
            member_ids,
            {
                "type": "shared_space_changed",
                "space_id": space_id,
                "action": "space_deleted",
                "actor": {"user_id": user_id, "via": "user"},
            },
        )
        logger.info("shared_space.deleted", space=space_id, by=user_id)

    # --- Members / invites ---

    async def invite(
        self,
        *,
        space_id: str,
        actor_id: str,
        target_user_id: str,
        role: SharedSpaceRole,
    ) -> MemberView:
        if role not in _INVITE_ROLES:
            raise ValidationError("邀请角色只能是 editor 或 viewer")
        if target_user_id == actor_id:
            raise ValidationError("不能邀请自己")
        space, actor = await self._require_accepted_member(space_id, actor_id)
        if actor.role != "owner":
            raise AuthorizationError("仅所有者可邀请成员")

        if not self._invite_limiter.allow(actor_id):
            raise RateLimitedError("邀请过于频繁，请稍后再试", retry_after=60)

        count = await self._spaces.count_members(space_id)
        if count >= self._max_members:
            raise QuotaExceededError(
                f"成员数已达上限（{self._max_members}）",
                dimension="shared_space_members",
            )

        target = await self._users.get_by_id(target_user_id)
        if target is None or getattr(target, "status", "active") != "active":
            raise NotFoundError("用户不存在")

        # Invite gate = discoverable (D3); independent of who_can_dm.
        settings = await self._directory.get(target_user_id)
        if settings is not None and not settings.discoverable:
            raise NotFoundError("用户不存在")

        if await self._blocks.is_blocked_between(actor_id, target_user_id):
            raise ValidationError("无法邀请该用户")

        existing = await self._spaces.get_member(space_id, target_user_id)
        if existing is not None:
            if existing.state == "accepted":
                raise ConflictError("该用户已是成员")
            raise ConflictError("邀请已发送，等待对方处理")

        member = await self._spaces.add_member(
            space_id=space_id,
            user_id=target_user_id,
            role=role,
            state="pending",
            invited_by=actor_id,
        )
        await self._record_and_fanout(
            space_id=space_id,
            actor_user_id=actor_id,
            actor_via="user",
            action="member_invited",
            detail={"target_user_id": target_user_id, "role": role},
        )
        # Invite delivery default: firehose event (not IM official message).
        await self._events.publish(
            [target_user_id],
            {
                "type": "shared_space_invite",
                "space_id": space_id,
                "space_name": space.name,
                "from_user_id": actor_id,
                "role": role,
            },
        )
        return await self._member_view(member, target)

    async def accept_invite(self, *, space_id: str, user_id: str) -> SpaceView:
        space = await self._spaces.get_space(space_id)
        member = await self._spaces.get_member(space_id, user_id)
        if space is None or member is None or member.state != "pending":
            raise NotFoundError("邀请不存在")
        await self._spaces.set_member_state(space_id, user_id, state="accepted")
        await self._record_and_fanout(
            space_id=space_id,
            actor_user_id=user_id,
            actor_via="user",
            action="member_accepted",
        )
        return await self.get_space(space_id=space_id, user_id=user_id)

    async def reject_invite(self, *, space_id: str, user_id: str) -> None:
        member = await self._spaces.get_member(space_id, user_id)
        if member is None or member.state != "pending":
            raise NotFoundError("邀请不存在")
        await self._spaces.remove_member(space_id, user_id)
        await self._record_and_fanout(
            space_id=space_id,
            actor_user_id=user_id,
            actor_via="user",
            action="member_rejected",
        )

    async def list_pending_invites(self, *, user_id: str) -> list[SpaceView]:
        rows = await self._spaces.list_pending_for_user(user_id)
        out: list[SpaceView] = []
        for space, member in rows:
            count = await self._spaces.count_members(space.id)
            out.append(
                SpaceView(
                    id=space.id,
                    name=space.name,
                    owner_user_id=space.owner_user_id,
                    my_role=member.role,  # type: ignore[arg-type]
                    my_state="pending",
                    member_count=count,
                    created_at=space.created_at,
                    updated_at=space.updated_at,
                )
            )
        return out

    async def list_members(self, *, space_id: str, user_id: str) -> list[MemberView]:
        await self._require_accepted_member(space_id, user_id)
        members = await self._spaces.list_members(space_id)
        users = await self._users.get_by_ids([m.user_id for m in members])
        return [await self._member_view(m, users.get(m.user_id)) for m in members]

    async def change_role(
        self,
        *,
        space_id: str,
        actor_id: str,
        target_user_id: str,
        role: SharedSpaceRole,
    ) -> MemberView:
        if role not in _INVITE_ROLES:
            raise ValidationError("角色只能改为 editor 或 viewer")
        _, actor = await self._require_accepted_member(space_id, actor_id)
        if actor.role != "owner":
            raise AuthorizationError("仅所有者可改角色")
        target = await self._spaces.get_member(space_id, target_user_id)
        if target is None or target.state != "accepted":
            raise NotFoundError("成员不存在")
        if target.role == "owner":
            raise ValidationError("不能变更所有者角色")
        await self._spaces.set_member_role(space_id, target_user_id, role=role)
        await self._record_and_fanout(
            space_id=space_id,
            actor_user_id=actor_id,
            actor_via="user",
            action="member_role_changed",
            detail={"target_user_id": target_user_id, "role": role},
        )
        user = await self._users.get_by_id(target_user_id)
        refreshed = await self._spaces.get_member(space_id, target_user_id)
        assert refreshed is not None
        return await self._member_view(refreshed, user)

    async def remove_member(
        self, *, space_id: str, actor_id: str, target_user_id: str
    ) -> None:
        """Owner removes a member (not themselves / not the owner row)."""
        _, actor = await self._require_accepted_member(space_id, actor_id)
        if actor.role != "owner":
            raise AuthorizationError("仅所有者可移除成员")
        if target_user_id == actor_id:
            raise ValidationError("所有者不能移除自己；请删除空间或转让（v1 不支持转让）")
        target = await self._spaces.get_member(space_id, target_user_id)
        if target is None:
            raise NotFoundError("成员不存在")
        if target.role == "owner":
            raise ValidationError("不能移除所有者")
        await self._spaces.remove_member(space_id, target_user_id)
        await self._record_and_fanout(
            space_id=space_id,
            actor_user_id=actor_id,
            actor_via="user",
            action="member_removed",
            detail={"target_user_id": target_user_id},
        )

    async def leave(self, *, space_id: str, user_id: str) -> None:
        space, member = await self._require_accepted_member(space_id, user_id)
        if member.role == "owner":
            raise ValidationError("所有者不能退出；请删除空间")
        await self._spaces.remove_member(space_id, user_id)
        await self._record_and_fanout(
            space_id=space.id,
            actor_user_id=user_id,
            actor_via="user",
            action="member_left",
        )

    # --- Auth helpers for workspace / mounts ---

    async def require_member_for_ws(
        self, *, space_id: str, user_id: str
    ) -> tuple[SharedSpace, SharedSpaceMember]:
        """Resolve ``shared:<id>`` for file APIs — non-member → 404."""
        return await self._require_accepted_member(space_id, user_id)

    async def resolve_mount_access(
        self, *, space_id: str, user_id: str
    ) -> MountAccess | None:
        """Realtime gate for tool-call granularity. ``None`` = no longer a member."""
        member = await self._spaces.get_member(space_id, user_id)
        if member is None or member.state != "accepted":
            return None
        role: SharedSpaceRole = member.role  # type: ignore[assignment]
        return MountAccess(mode=role_to_mount_mode(role), role=role)

    async def assert_can_write_files(self, *, space_id: str, user_id: str) -> SharedSpaceMember:
        _, member = await self._require_accepted_member(space_id, user_id)
        if not can_write(member.role):  # type: ignore[arg-type]
            raise AuthorizationError("只读成员不能写入共享空间")
        return member

    def check_capacity(self, space_id: str, *, incoming_bytes: int = 0) -> None:
        """Refuse writes that would push the space over the soft disk cap."""
        root = shared_workspace_root_path(space_id)
        used = _dir_size(root) if root.is_dir() else 0
        if used + max(0, incoming_bytes) > self._max_bytes:
            raise QuotaExceededError(
                f"共享空间容量已达上限（{self._max_bytes} 字节）",
                dimension="shared_space_bytes",
            )

    def storage_key(self, space_id: str) -> str:
        return shared_workspace_storage_key(space_id)

    # --- Change log ---

    async def list_events(
        self, *, space_id: str, user_id: str, limit: int = 50, before_id: str | None = None
    ) -> list[SharedSpaceEvent]:
        await self._require_accepted_member(space_id, user_id)
        return list(await self._spaces.list_events(space_id, limit=limit, before_id=before_id))

    async def record_file_change(
        self,
        *,
        space_id: str,
        actor_user_id: str,
        actor_via: Literal["user", "agent"],
        action: str,
        path: str | None = None,
        detail: dict | None = None,
    ) -> None:
        await self._record_and_fanout(
            space_id=space_id,
            actor_user_id=actor_user_id,
            actor_via=actor_via,
            action=action,
            path=path,
            detail=detail,
        )

    # --- Block linkage (D3) ---

    async def on_users_blocked(self, user_a: str, user_b: str) -> int:
        """Auto-reject pending invites between a newly blocked pair; do not kick members."""
        n = await self._spaces.delete_pending_between(user_a, user_b)
        if n:
            logger.info(
                "shared_space.pending_cleared_on_block",
                user_a=user_a,
                user_b=user_b,
                count=n,
            )
        return n

    # --- Account cleanup ---

    async def cleanup_for_deleted_user(self, user_id: str) -> None:
        """Owner → delete spaces + disk; member → drop membership rows; clear pending."""
        owned_ids = list(await self._spaces.list_owned_space_ids(user_id))
        for space_id in owned_ids:
            members = await self._spaces.list_members(space_id)
            notify = [m.user_id for m in members if m.user_id != user_id]
            await self._spaces.delete_space(space_id)
            shared_mount_store.revoke_space_everywhere(space_id)
            self._rm_disk(space_id)
            if notify:
                await self._events.publish(
                    notify,
                    {
                        "type": "shared_space_changed",
                        "space_id": space_id,
                        "action": "space_deleted",
                        "actor": {"user_id": user_id, "via": "user"},
                        "reason": "owner_account_deleted",
                    },
                )
        # Remaining memberships (as non-owner member or pending invitee).
        await self._spaces.delete_all_memberships_for_user(user_id)
        logger.info(
            "shared_space.cleanup_account",
            user=user_id,
            owned_deleted=len(owned_ids),
        )

    # --- Internals ---

    async def _require_accepted_member(
        self, space_id: str, user_id: str
    ) -> tuple[SharedSpace, SharedSpaceMember]:
        space = await self._spaces.get_space(space_id)
        member = await self._spaces.get_member(space_id, user_id)
        if space is None or member is None or member.state != "accepted":
            raise NotFoundError("共享空间不存在")
        return space, member

    async def _member_view(
        self, member: SharedSpaceMember, user: User | None
    ) -> MemberView:
        return MemberView(
            user_id=member.user_id,
            role=member.role,  # type: ignore[arg-type]
            state=member.state,  # type: ignore[arg-type]
            invited_by=member.invited_by,
            joined_at=member.joined_at,
            display_name=getattr(user, "display_name", None) if user else None,
            username=getattr(user, "username", None) if user else None,
        )

    async def _record_and_fanout(
        self,
        *,
        space_id: str,
        actor_user_id: str | None,
        actor_via: str,
        action: str,
        path: str | None = None,
        detail: dict | None = None,
    ) -> None:
        await self._spaces.add_event(
            space_id=space_id,
            actor_user_id=actor_user_id,
            actor_via=actor_via,
            action=action,
            path=path,
            detail=detail,
        )
        members = await self._spaces.list_members(space_id)
        recipient_ids = [
            m.user_id for m in members if m.state == "accepted"
        ]
        if not recipient_ids:
            return
        event: dict[str, Any] = {
            "type": "shared_space_changed",
            "space_id": space_id,
            "action": action,
            "actor": {"user_id": actor_user_id, "via": actor_via},
        }
        if path is not None:
            event["path"] = path
        if detail is not None:
            event["detail"] = detail
        await self._events.publish(recipient_ids, event)

    @staticmethod
    def _rm_disk(space_id: str) -> None:
        root = shared_workspace_root_path(space_id)
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)


def _dir_size(root: Path) -> int:
    total = 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total
