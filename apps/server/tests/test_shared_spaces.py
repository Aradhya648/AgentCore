"""Unit tests for SharedSpaceService (fake repos, no DB).

Covers member lifecycle, non-member 404, role demotion immediacy, mount-mode
mapping, block linkage (pending auto-reject, no kick), account cleanup, and
space-level lock key stability.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agentcore.core.errors import (
    NotFoundError,
    QuotaExceededError,
)
from agentcore.core.types import new_id
from agentcore.middleware.rate_limit import FixedWindowRateLimiter
from agentcore.shared_spaces.service import SharedSpaceService
from agentcore.shared_spaces.types import can_write, role_to_mount_mode
from agentcore.workspace import shared_mount_store
from agentcore.workspace.locks import workspace_lock
from agentcore.workspace.protocol import OutsideWorkspace
from agentcore.workspace.server import ServerWorkspace
from agentcore.workspace.shared_mounts import SharedMount
from agentcore.workspace.shared_paths import shared_workspace_storage_key

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class FakeUsers:
    def __init__(self) -> None:
        self._by_id: dict = {}

    def add(self, username, *, status="active"):
        user = SimpleNamespace(
            user_id=new_id(),
            username=username,
            display_name=username,
            status=status,
            role="user",
        )
        self._by_id[user.user_id] = user
        return user

    async def get_by_id(self, user_id):
        return self._by_id.get(user_id)

    async def get_by_ids(self, user_ids):
        return {uid: self._by_id[uid] for uid in user_ids if uid in self._by_id}

    async def search(self, query, *, limit=20):
        q = query.strip().lower()
        return [
            u
            for u in self._by_id.values()
            if u.username.lower() == q and u.status == "active"
        ][:limit]


class FakeBlocks:
    def __init__(self) -> None:
        self._pairs: set[tuple[str, str]] = set()

    async def block(self, a, b):
        self._pairs.add((a, b))

    async def is_blocked_between(self, a, b):
        return (a, b) in self._pairs or (b, a) in self._pairs


class FakeDirectory:
    def __init__(self) -> None:
        self._rows: dict = {}

    def set(self, user_id, *, discoverable=True, who_can_dm="anyone"):
        self._rows[user_id] = SimpleNamespace(
            discoverable=discoverable, who_can_dm=who_can_dm
        )

    async def get(self, user_id):
        return self._rows.get(user_id)


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[tuple[list, dict]] = []

    async def publish(self, user_ids, event):
        self.published.append((list(user_ids), event))


class FakeSpaces:
    def __init__(self) -> None:
        self._spaces: dict = {}
        self._members: list = []
        self._events: list = []
        self._seq = 0

    def _now(self):
        self._seq += 1
        return _EPOCH + timedelta(seconds=self._seq)

    async def create_space(self, *, owner_user_id, name):
        space = SimpleNamespace(
            id=new_id(),
            owner_user_id=owner_user_id,
            name=name,
            created_at=self._now(),
            updated_at=self._now(),
        )
        self._spaces[space.id] = space
        self._members.append(
            SimpleNamespace(
                space_id=space.id,
                user_id=owner_user_id,
                role="owner",
                state="accepted",
                invited_by=None,
                joined_at=self._now(),
            )
        )
        return space

    async def get_space(self, space_id):
        return self._spaces.get(space_id)

    async def update_space(self, space_id, *, name):
        space = self._spaces[space_id]
        space.name = name
        space.updated_at = self._now()
        return space

    async def delete_space(self, space_id):
        if space_id not in self._spaces:
            return False
        del self._spaces[space_id]
        self._members = [m for m in self._members if m.space_id != space_id]
        self._events = [e for e in self._events if e.space_id != space_id]
        return True

    async def count_owned_spaces(self, owner_user_id):
        return sum(1 for s in self._spaces.values() if s.owner_user_id == owner_user_id)

    async def list_spaces_for_user(self, user_id, *, state="accepted"):
        out = []
        for m in self._members:
            if m.user_id == user_id and m.state == state and m.space_id in self._spaces:
                out.append((self._spaces[m.space_id], m))
        return out

    async def list_owned_space_ids(self, owner_user_id):
        return [s.id for s in self._spaces.values() if s.owner_user_id == owner_user_id]

    async def get_member(self, space_id, user_id):
        return next(
            (
                m
                for m in self._members
                if m.space_id == space_id and m.user_id == user_id
            ),
            None,
        )

    async def list_members(self, space_id):
        return [m for m in self._members if m.space_id == space_id]

    async def count_members(self, space_id):
        return sum(1 for m in self._members if m.space_id == space_id)

    async def add_member(self, *, space_id, user_id, role, state, invited_by):
        m = SimpleNamespace(
            space_id=space_id,
            user_id=user_id,
            role=role,
            state=state,
            invited_by=invited_by,
            joined_at=self._now(),
        )
        self._members.append(m)
        return m

    async def set_member_state(self, space_id, user_id, *, state):
        m = await self.get_member(space_id, user_id)
        m.state = state

    async def set_member_role(self, space_id, user_id, *, role):
        m = await self.get_member(space_id, user_id)
        m.role = role

    async def remove_member(self, space_id, user_id):
        self._members = [
            m
            for m in self._members
            if not (m.space_id == space_id and m.user_id == user_id)
        ]

    async def list_pending_for_user(self, user_id):
        return await self.list_spaces_for_user(user_id, state="pending")

    async def delete_pending_between(self, user_a, user_b):
        before = len(self._members)
        self._members = [
            m
            for m in self._members
            if not (
                m.state == "pending"
                and (
                    (m.user_id == user_a and m.invited_by == user_b)
                    or (m.user_id == user_b and m.invited_by == user_a)
                )
            )
        ]
        return before - len(self._members)

    async def delete_all_memberships_for_user(self, user_id):
        ids = [m.space_id for m in self._members if m.user_id == user_id]
        self._members = [m for m in self._members if m.user_id != user_id]
        return ids

    async def add_event(self, *, space_id, actor_user_id, actor_via, action, path=None, detail=None):
        e = SimpleNamespace(
            id=new_id(),
            space_id=space_id,
            actor_user_id=actor_user_id,
            actor_via=actor_via,
            action=action,
            path=path,
            detail=detail,
            created_at=self._now(),
        )
        self._events.append(e)
        return e

    async def list_events(self, space_id, *, limit=50, before_id=None):
        rows = [e for e in self._events if e.space_id == space_id]
        rows.sort(key=lambda e: e.created_at, reverse=True)
        return rows[:limit]


def _svc(**kwargs):
    users = kwargs.pop("users", FakeUsers())
    spaces = kwargs.pop("spaces", FakeSpaces())
    blocks = kwargs.pop("blocks", FakeBlocks())
    directory = kwargs.pop("directory", FakeDirectory())
    events = kwargs.pop("events", FakeEvents())
    return SharedSpaceService(
        spaces=spaces,
        users=users,
        blocks=blocks,
        directory=directory,
        events=events,
        invite_limiter=FixedWindowRateLimiter(max_requests=100, window_seconds=3600),
        **kwargs,
    ), users, spaces, blocks, directory, events


@pytest.mark.asyncio
async def test_create_invite_accept_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shutil.rmtree", lambda *a, **k: None
    )
    svc, users, spaces, *_ = _svc()
    owner = users.add("owner")
    peer = users.add("peer")
    space = await svc.create_space(owner_id=owner.user_id, name="协作盘")
    assert space.my_role == "owner"

    await svc.invite(
        space_id=space.id,
        actor_id=owner.user_id,
        target_user_id=peer.user_id,
        role="editor",
    )
    pending = await svc.list_pending_invites(user_id=peer.user_id)
    assert len(pending) == 1

    with pytest.raises(NotFoundError):
        await svc.get_space(space_id=space.id, user_id=peer.user_id)

    accepted = await svc.accept_invite(space_id=space.id, user_id=peer.user_id)
    assert accepted.my_role == "editor"
    assert accepted.my_state == "accepted"


@pytest.mark.asyncio
async def test_non_member_404(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    svc, users, *_ = _svc()
    owner = users.add("owner")
    stranger = users.add("stranger")
    space = await svc.create_space(owner_id=owner.user_id, name="私密")
    with pytest.raises(NotFoundError):
        await svc.get_space(space_id=space.id, user_id=stranger.user_id)
    with pytest.raises(NotFoundError):
        await svc.require_member_for_ws(space_id=space.id, user_id=stranger.user_id)


@pytest.mark.asyncio
async def test_demotion_immediate_for_mount_access(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    svc, users, *_ = _svc()
    owner = users.add("owner")
    peer = users.add("peer")
    space = await svc.create_space(owner_id=owner.user_id, name="盘")
    await svc.invite(
        space_id=space.id,
        actor_id=owner.user_id,
        target_user_id=peer.user_id,
        role="editor",
    )
    await svc.accept_invite(space_id=space.id, user_id=peer.user_id)

    access = await svc.resolve_mount_access(space_id=space.id, user_id=peer.user_id)
    assert access is not None
    assert access.mode == "write"
    assert role_to_mount_mode(access.role) == "write"

    await svc.change_role(
        space_id=space.id,
        actor_id=owner.user_id,
        target_user_id=peer.user_id,
        role="viewer",
    )
    access2 = await svc.resolve_mount_access(space_id=space.id, user_id=peer.user_id)
    assert access2 is not None
    assert access2.mode == "readonly"
    assert not can_write(access2.role)

    await svc.remove_member(
        space_id=space.id, actor_id=owner.user_id, target_user_id=peer.user_id
    )
    assert await svc.resolve_mount_access(space_id=space.id, user_id=peer.user_id) is None


@pytest.mark.asyncio
async def test_block_rejects_pending_not_members(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    svc, users, spaces, blocks, *_ = _svc()
    owner = users.add("owner")
    peer = users.add("peer")
    space = await svc.create_space(owner_id=owner.user_id, name="盘")
    await svc.invite(
        space_id=space.id,
        actor_id=owner.user_id,
        target_user_id=peer.user_id,
        role="viewer",
    )
    assert await spaces.get_member(space.id, peer.user_id) is not None

    await blocks.block(owner.user_id, peer.user_id)
    n = await svc.on_users_blocked(owner.user_id, peer.user_id)
    assert n == 1
    assert await spaces.get_member(space.id, peer.user_id) is None

    # Accepted member is NOT auto-kicked.
    peer2 = users.add("peer2")
    await svc.invite(
        space_id=space.id,
        actor_id=owner.user_id,
        target_user_id=peer2.user_id,
        role="editor",
    )
    await svc.accept_invite(space_id=space.id, user_id=peer2.user_id)
    await blocks.block(owner.user_id, peer2.user_id)
    n2 = await svc.on_users_blocked(owner.user_id, peer2.user_id)
    assert n2 == 0
    member = await spaces.get_member(space.id, peer2.user_id)
    assert member is not None and member.state == "accepted"


@pytest.mark.asyncio
async def test_cleanup_owner_deletes_space(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    removed = []
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shutil.rmtree",
        lambda p, ignore_errors=False: removed.append(str(p)),
    )
    svc, users, spaces, *_ = _svc()
    owner = users.add("owner")
    peer = users.add("peer")
    space = await svc.create_space(owner_id=owner.user_id, name="盘")
    await svc.invite(
        space_id=space.id,
        actor_id=owner.user_id,
        target_user_id=peer.user_id,
        role="editor",
    )
    await svc.accept_invite(space_id=space.id, user_id=peer.user_id)

    await svc.cleanup_for_deleted_user(owner.user_id)
    assert await spaces.get_space(space.id) is None
    assert removed  # disk wiped


@pytest.mark.asyncio
async def test_cleanup_member_drops_membership(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shutil.rmtree", lambda *a, **k: None
    )
    svc, users, spaces, *_ = _svc()
    owner = users.add("owner")
    peer = users.add("peer")
    space = await svc.create_space(owner_id=owner.user_id, name="盘")
    await svc.invite(
        space_id=space.id,
        actor_id=owner.user_id,
        target_user_id=peer.user_id,
        role="editor",
    )
    await svc.accept_invite(space_id=space.id, user_id=peer.user_id)

    await svc.cleanup_for_deleted_user(peer.user_id)
    assert await spaces.get_space(space.id) is not None
    assert await spaces.get_member(space.id, peer.user_id) is None


@pytest.mark.asyncio
async def test_shared_mount_gate_and_lock(tmp_path, monkeypatch):
    """Agent write to shared mount: realtime gate + space-level lock key."""

    class _NullSandbox:
        async def execute(self, *a, **k):
            raise NotImplementedError

    root = tmp_path / "primary"
    root.mkdir()
    space_id = new_id()
    space_root = tmp_path / "shared" / space_id
    space_root.mkdir(parents=True)

    monkeypatch.setattr(
        "agentcore.workspace.shared_paths.shared_workspace_root_path",
        lambda sid: tmp_path / "shared" / sid,
    )
    # ServerWorkspace imports the name into its module namespace.
    monkeypatch.setattr(
        "agentcore.workspace.server.shared_workspace_root_path",
        lambda sid: tmp_path / "shared" / sid,
    )

    roles = {"mode": "write"}

    async def gate(sid: str):
        assert sid == space_id
        return roles["mode"]

    backend = ServerWorkspace(root=root, sandbox=_NullSandbox())  # type: ignore[arg-type]
    backend.attach_shared_mounts(
        {"docs": SharedMount(alias="docs", space_id=space_id, label="docs", mode="write")},
        gate=gate,
    )

    await backend.write("shared/docs/a.txt", "hello")
    assert (space_root / "a.txt").read_text(encoding="utf-8") == "hello"

    roles["mode"] = "readonly"
    with pytest.raises(OutsideWorkspace):
        await backend.write("shared/docs/b.txt", "nope")

    roles["mode"] = None
    with pytest.raises(OutsideWorkspace):
        await backend.read("shared/docs/a.txt")

    # Lock key is cross-user stable.
    key = shared_workspace_storage_key(space_id)
    assert key == f"workspaces/shared/{space_id}"
    order: list[str] = []

    async def hold(tag: str):
        async with workspace_lock(key):
            order.append(f"enter-{tag}")
            order.append(f"leave-{tag}")

    import asyncio

    await asyncio.gather(hold("a"), hold("b"))
    assert order[0].startswith("enter-")
    assert order[1].startswith("leave-")


@pytest.mark.asyncio
async def test_role_to_mount_mapping():
    assert role_to_mount_mode("owner") == "write"
    assert role_to_mount_mode("editor") == "write"
    assert role_to_mount_mode("viewer") == "readonly"


@pytest.mark.asyncio
async def test_quota_max_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    svc, users, *_ = _svc(max_spaces_per_owner=1)
    owner = users.add("owner")
    await svc.create_space(owner_id=owner.user_id, name="one")
    with pytest.raises(QuotaExceededError):
        await svc.create_space(owner_id=owner.user_id, name="two")


@pytest.mark.asyncio
async def test_undiscoverable_cannot_invite(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentcore.shared_spaces.service.shared_workspace_root_path",
        lambda sid: tmp_path / sid,
    )
    directory = FakeDirectory()
    svc, users, _spaces, _blocks, _directory, _events = _svc(directory=directory)
    owner = users.add("owner")
    peer = users.add("hidden")
    directory.set(peer.user_id, discoverable=False)
    space = await svc.create_space(owner_id=owner.user_id, name="盘")
    with pytest.raises(NotFoundError):
        await svc.invite(
            space_id=space.id,
            actor_id=owner.user_id,
            target_user_id=peer.user_id,
            role="viewer",
        )


@pytest.mark.asyncio
async def test_mount_store_revoke_on_space_delete():
    shared_mount_store.clear_all_for_tests()
    shared_mount_store.add_mount(
        "conv1", space_id="space1", label="A", mode="write", alias_hint="A"
    )
    shared_mount_store.revoke_space_everywhere("space1")
    assert shared_mount_store.list_mounts("conv1") == []
