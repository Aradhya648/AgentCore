"""Unit tests for MessagingService using in-memory fake repositories (no DB).

Covers the 消息 page (找人 IM) policy: people-search visibility, the start-dm
gates (self / unknown / disabled / blocked / contacts-only), send-message member
+ block + message-request handling and idempotency, list/unread, read cursor,
blocking, and directory settings. Mirrors test_auth_service.py's fake-repo style.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.core.errors import (
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from agentcore.core.types import new_id
from agentcore.messaging import MessagingService

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class FakeUsers:
    def __init__(self) -> None:
        self._by_id: dict = {}

    def add(self, username, *, status="active", display_name=None, role="user"):
        from types import SimpleNamespace

        user = SimpleNamespace(
            user_id=new_id(),
            username=username,
            display_name=display_name or username,
            status=status,
            role=role,
        )
        self._by_id[user.user_id] = user
        return user

    async def get_by_id(self, user_id):
        return self._by_id.get(user_id)

    async def get_by_ids(self, user_ids):
        return {uid: self._by_id[uid] for uid in user_ids if uid in self._by_id}

    async def search(self, query, *, limit=20):
        q = query.strip().lower()
        if not q:
            return []
        hits = [u for u in self._by_id.values() if u.username.lower() == q and u.status == "active"]
        return hits[:limit]


class FakeChats:
    """In-memory chats/members/messages with a counter-driven clock so message
    ordering is deterministic (real created_at could tie on fast inserts).
    """

    def __init__(self) -> None:
        self._chats: dict = {}
        self._members: list = []
        self._messages: list = []
        self._seq = 0

    def _now(self):
        self._seq += 1
        return _EPOCH + timedelta(seconds=self._seq)

    @staticmethod
    def dm_key(user_a, user_b):
        return ":".join(sorted([user_a, user_b]))

    async def get_dm(self, user_a, user_b):
        key = self.dm_key(user_a, user_b)
        return next((c for c in self._chats.values() if c.dm_key == key), None)

    async def create_dm(self, *, creator_id, peer_id, peer_state="pending"):
        from types import SimpleNamespace

        chat = SimpleNamespace(
            id=new_id(),
            type="dm",
            created_by=creator_id,
            dm_key=self.dm_key(creator_id, peer_id),
            title=None,
            avatar_url=None,
            auto_join=False,
            last_message_at=None,
            last_message_preview=None,
        )
        self._chats[chat.id] = chat
        for uid, state in ((creator_id, "accepted"), (peer_id, peer_state)):
            self._members.append(
                SimpleNamespace(
                    chat_id=chat.id,
                    user_id=uid,
                    role="member",
                    state=state,
                    pinned=False,
                    muted=False,
                    muted_by_admin=False,
                    last_read_at=None,
                    last_read_message_id=None,
                    joined_at=self._now(),
                )
            )
        return chat

    async def create_group(self, *, title="群", auto_join=False, member_ids=()):
        """Test helper: a group chat (the real row is created by a migration)."""
        from types import SimpleNamespace

        chat = SimpleNamespace(
            id=new_id(),
            type="group",
            created_by=None,
            dm_key=None,
            title=title,
            avatar_url=None,
            auto_join=auto_join,
            last_message_at=None,
            last_message_preview=None,
        )
        self._chats[chat.id] = chat
        for uid in member_ids:
            await self.add_member(chat.id, uid)
        return chat

    async def list_auto_join_chats(self):
        return [c for c in self._chats.values() if getattr(c, "auto_join", False)]

    async def add_member(self, chat_id, user_id, *, role="member", state="accepted", pinned=False):
        from types import SimpleNamespace

        if await self.get_member(chat_id, user_id) is not None:
            return
        self._members.append(
            SimpleNamespace(
                chat_id=chat_id,
                user_id=user_id,
                role=role,
                state=state,
                pinned=pinned,
                muted=False,
                muted_by_admin=False,
                last_read_at=None,
                last_read_message_id=None,
                joined_at=self._now(),
            )
        )

    async def get_chat(self, chat_id):
        return self._chats.get(chat_id)

    async def get_member(self, chat_id, user_id):
        return next(
            (m for m in self._members if m.chat_id == chat_id and m.user_id == user_id),
            None,
        )

    async def list_members(self, chat_id):
        return [m for m in self._members if m.chat_id == chat_id]

    async def remove_member(self, chat_id, user_id):
        self._members = [
            m for m in self._members if not (m.chat_id == chat_id and m.user_id == user_id)
        ]

    async def set_membership_flags(self, chat_id, user_id, *, muted=None, pinned=None):
        member = await self.get_member(chat_id, user_id)
        if member is None:
            return
        if muted is not None:
            member.muted = muted
        if pinned is not None:
            member.pinned = pinned

    async def set_admin_mute(self, chat_id, user_id, *, muted_by_admin):
        member = await self.get_member(chat_id, user_id)
        if member is not None:
            member.muted_by_admin = muted_by_admin

    async def list_memberships(self, user_id):
        rows = [(self._chats[m.chat_id], m) for m in self._members if m.user_id == user_id]
        rows.sort(key=lambda cm: cm[0].last_message_at or _EPOCH, reverse=True)
        return rows

    async def peer_ids_for(self, chat_ids, *, exclude_user_id):
        out: dict = {}
        for m in self._members:
            if m.chat_id in chat_ids and m.user_id != exclude_user_id:
                out.setdefault(m.chat_id, m.user_id)
        return out

    async def add_message(
        self,
        *,
        chat_id,
        sender_user_id,
        content,
        sender_type="user",
        content_type="text",
        attachments=None,
        payload=None,
        reply_to_message_id=None,
        client_msg_id=None,
    ):
        from types import SimpleNamespace

        if client_msg_id is not None and sender_user_id is not None:
            existing = next(
                (
                    m
                    for m in self._messages
                    if m.chat_id == chat_id
                    and m.sender_user_id == sender_user_id
                    and m.client_msg_id == client_msg_id
                ),
                None,
            )
            if existing is not None:
                return existing
        msg = SimpleNamespace(
            id=new_id(),
            chat_id=chat_id,
            sender_user_id=sender_user_id,
            sender_type=sender_type,
            content=content,
            content_type=content_type,
            attachments=attachments or [],
            payload=payload,
            reply_to_message_id=reply_to_message_id,
            client_msg_id=client_msg_id,
            created_at=self._now(),
        )
        self._messages.append(msg)
        chat = self._chats[chat_id]
        chat.last_message_at = msg.created_at
        chat.last_message_preview = (content or "")[:200]
        return msg

    async def list_messages(self, chat_id, *, limit=50, offset=0):
        rows = sorted(
            (m for m in self._messages if m.chat_id == chat_id),
            key=lambda m: m.created_at,
        )
        return rows[offset : offset + limit], len(rows)

    async def mark_read(self, chat_id, user_id, *, last_read_message_id, last_read_at=None):
        member = await self.get_member(chat_id, user_id)
        member.last_read_message_id = last_read_message_id
        member.last_read_at = last_read_at or self._now()

    async def accept_request(self, chat_id, user_id):
        member = await self.get_member(chat_id, user_id)
        member.state = "accepted"

    async def unread_counts(self, user_id):
        out: dict = {}
        my_chats = {m.chat_id: m for m in self._members if m.user_id == user_id}
        for msg in self._messages:
            member = my_chats.get(msg.chat_id)
            if member is None or msg.sender_user_id == user_id:
                continue
            if member.last_read_at is None or msg.created_at > member.last_read_at:
                out[msg.chat_id] = out.get(msg.chat_id, 0) + 1
        return out


class FakeBlocks:
    def __init__(self) -> None:
        self._pairs: set = set()

    async def is_blocked_between(self, user_a, user_b):
        return (user_a, user_b) in self._pairs or (user_b, user_a) in self._pairs

    async def block(self, user_id, blocked_user_id):
        self._pairs.add((user_id, blocked_user_id))

    async def unblock(self, user_id, blocked_user_id):
        self._pairs.discard((user_id, blocked_user_id))

    async def list_blocked(self, user_id):
        return [b for (a, b) in self._pairs if a == user_id]


class FakeDirectory:
    def __init__(self) -> None:
        self._by_user: dict = {}

    async def get(self, user_id):
        return self._by_user.get(user_id)

    async def upsert(self, user_id, *, discoverable=None, who_can_dm=None):
        from types import SimpleNamespace

        settings = self._by_user.get(user_id)
        if settings is None:
            settings = SimpleNamespace(user_id=user_id, discoverable=True, who_can_dm="anyone")
            self._by_user[user_id] = settings
        if discoverable is not None:
            settings.discoverable = discoverable
        if who_can_dm is not None:
            settings.who_can_dm = who_can_dm
        return settings

    def set(self, user_id, *, discoverable=True, who_can_dm="anyone"):
        from types import SimpleNamespace

        self._by_user[user_id] = SimpleNamespace(
            user_id=user_id, discoverable=discoverable, who_can_dm=who_can_dm
        )


class FakeEvents:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, user_ids, event):
        self.published.append((list(user_ids), event))


def _make():
    users = FakeUsers()
    chats = FakeChats()
    blocks = FakeBlocks()
    directory = FakeDirectory()
    events = FakeEvents()
    svc = MessagingService(
        users=users,
        chats=chats,
        blocks=blocks,
        directory=directory,
        events=events,
    )
    return svc, users, chats, blocks, directory, events


# --- search_users ---


async def test_search_returns_exact_match():
    svc, users, *_ = _make()
    alice = users.add("alice")
    users.add("bob")
    hits = await svc.search_users(requester_id=alice.user_id, query="bob")
    assert [u.username for u in hits] == ["bob"]


async def test_search_excludes_self():
    svc, users, *_ = _make()
    alice = users.add("alice")
    hits = await svc.search_users(requester_id=alice.user_id, query="alice")
    assert hits == []


async def test_search_excludes_blocked_pair():
    svc, users, _chats, blocks, *_ = _make()
    alice = users.add("alice")
    carol = users.add("carol")
    await blocks.block(alice.user_id, carol.user_id)
    assert await svc.search_users(requester_id=alice.user_id, query="carol") == []
    # symmetric: carol also cannot find alice
    assert await svc.search_users(requester_id=carol.user_id, query="alice") == []


async def test_search_excludes_undiscoverable():
    svc, users, _chats, _blocks, directory, _events = _make()
    alice = users.add("alice")
    carol = users.add("carol")
    directory.set(carol.user_id, discoverable=False)
    assert await svc.search_users(requester_id=alice.user_id, query="carol") == []


# --- start_dm ---


async def test_start_dm_creates_chat_peer_pending():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    view = await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)
    assert view.chat.type == "dm"
    assert view.peer.user_id == bob.user_id
    assert view.member.state == "accepted"
    peer_member = await chats.get_member(view.chat.id, bob.user_id)
    assert peer_member.state == "pending"


async def test_start_dm_reuses_existing():
    svc, users, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    first = await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)
    # the peer opening it from their side resolves to the same chat row
    second = await svc.start_dm(requester_id=bob.user_id, peer_id=alice.user_id)
    assert first.chat.id == second.chat.id


async def test_start_dm_self_raises():
    svc, users, *_ = _make()
    alice = users.add("alice")
    with pytest.raises(ValidationError):
        await svc.start_dm(requester_id=alice.user_id, peer_id=alice.user_id)


async def test_start_dm_unknown_peer_raises():
    svc, users, *_ = _make()
    alice = users.add("alice")
    with pytest.raises(NotFoundError):
        await svc.start_dm(requester_id=alice.user_id, peer_id="ghost")


async def test_start_dm_disabled_peer_raises():
    svc, users, *_ = _make()
    alice = users.add("alice")
    banned = users.add("banned", status="disabled")
    with pytest.raises(NotFoundError):
        await svc.start_dm(requester_id=alice.user_id, peer_id=banned.user_id)


async def test_start_dm_blocked_raises():
    svc, users, _chats, blocks, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    await blocks.block(bob.user_id, alice.user_id)
    with pytest.raises(AuthorizationError):
        await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)


async def test_start_dm_contacts_only_raises():
    svc, users, _chats, _blocks, directory, _events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    directory.set(bob.user_id, who_can_dm="contacts")
    with pytest.raises(AuthorizationError):
        await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)


async def test_start_dm_reuse_skips_contacts_gate():
    svc, users, _chats, _blocks, directory, _events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    first = await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)
    # bob later locks down to contacts-only; the existing dm still reopens
    directory.set(bob.user_id, who_can_dm="contacts")
    again = await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)
    assert first.chat.id == again.chat.id


# --- send_message ---


async def test_send_message_non_member_404():
    svc, users, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    stranger = users.add("stranger")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    with pytest.raises(NotFoundError):
        await svc.send_message(chat_id=chat.id, sender_id=stranger.user_id, content="hi")


async def test_send_message_persists_and_fans_out():
    svc, users, _chats, _blocks, _directory, events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    msg = await svc.send_message(chat_id=chat.id, sender_id=alice.user_id, content="hello bob")
    assert msg.content == "hello bob"
    assert len(events.published) == 1
    recipients, event = events.published[0]
    assert set(recipients) == {alice.user_id, bob.user_id}
    assert event["type"] == "chat_message"
    assert event["message"]["id"] == msg.id


async def test_send_message_blocked_dm_raises():
    svc, users, _chats, blocks, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    await blocks.block(bob.user_id, alice.user_id)
    with pytest.raises(AuthorizationError):
        await svc.send_message(chat_id=chat.id, sender_id=alice.user_id, content="hi")


async def test_reply_accepts_pending_request():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    # alice's opening message leaves bob pending (a message request)
    await svc.send_message(chat_id=chat.id, sender_id=alice.user_id, content="hi bob")
    assert (await chats.get_member(chat.id, bob.user_id)).state == "pending"
    # bob replying accepts the request
    await svc.send_message(chat_id=chat.id, sender_id=bob.user_id, content="hey")
    assert (await chats.get_member(chat.id, bob.user_id)).state == "accepted"


async def test_send_message_idempotent_client_msg_id():
    svc, users, _chats, _blocks, _directory, events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    first = await svc.send_message(
        chat_id=chat.id, sender_id=alice.user_id, content="hi", client_msg_id="c1"
    )
    second = await svc.send_message(
        chat_id=chat.id, sender_id=alice.user_id, content="hi", client_msg_id="c1"
    )
    assert first.id == second.id
    page = await svc.list_messages(chat_id=chat.id, user_id=alice.user_id)
    assert page.total == 1


# --- list_chats / unread / mark_read ---


async def test_list_chats_resolves_peer_and_unread():
    svc, users, _chats, _blocks, _directory, _events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    await svc.send_message(chat_id=chat.id, sender_id=bob.user_id, content="m1")
    last = await svc.send_message(chat_id=chat.id, sender_id=bob.user_id, content="m2")

    views = await svc.list_chats(user_id=alice.user_id)
    assert len(views) == 1
    assert views[0].peer.user_id == bob.user_id
    assert views[0].unread == 2

    await svc.mark_read(chat_id=chat.id, user_id=alice.user_id, last_read_message_id=last.id)
    views = await svc.list_chats(user_id=alice.user_id)
    assert views[0].unread == 0


async def test_list_chats_orders_recent_first():
    svc, users, _chats, _blocks, _directory, _events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    carol = users.add("carol")
    chat_b = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    chat_c = (await svc.start_dm(requester_id=alice.user_id, peer_id=carol.user_id)).chat
    await svc.send_message(chat_id=chat_b.id, sender_id=alice.user_id, content="b")
    await svc.send_message(chat_id=chat_c.id, sender_id=alice.user_id, content="c")
    # chat_c has the most recent message -> it sorts first
    views = await svc.list_chats(user_id=alice.user_id)
    assert [v.chat.id for v in views] == [chat_c.id, chat_b.id]


# --- list_messages ---


async def test_list_messages_paginates():
    svc, users, _chats, _blocks, _directory, _events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    for i in range(5):
        await svc.send_message(chat_id=chat.id, sender_id=alice.user_id, content=f"m{i}")
    page = await svc.list_messages(chat_id=chat.id, user_id=alice.user_id, page=1, page_size=2)
    assert page.total == 5
    assert [m.content for m in page.messages] == ["m0", "m1"]
    page2 = await svc.list_messages(chat_id=chat.id, user_id=alice.user_id, page=2, page_size=2)
    assert [m.content for m in page2.messages] == ["m2", "m3"]


async def test_list_messages_non_member_404():
    svc, users, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    stranger = users.add("stranger")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    with pytest.raises(NotFoundError):
        await svc.list_messages(chat_id=chat.id, user_id=stranger.user_id)


async def test_mark_read_non_member_404():
    svc, users, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    stranger = users.add("stranger")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    with pytest.raises(NotFoundError):
        await svc.mark_read(chat_id=chat.id, user_id=stranger.user_id, last_read_message_id="x")


# --- blocking ---


async def test_block_self_raises():
    svc, users, *_ = _make()
    alice = users.add("alice")
    with pytest.raises(ValidationError):
        await svc.block_user(user_id=alice.user_id, target_id=alice.user_id)


async def test_block_unknown_target_raises():
    svc, users, *_ = _make()
    alice = users.add("alice")
    with pytest.raises(NotFoundError):
        await svc.block_user(user_id=alice.user_id, target_id="ghost")


async def test_block_list_and_unblock_roundtrip():
    svc, users, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    await svc.block_user(user_id=alice.user_id, target_id=bob.user_id)
    blocked = await svc.list_blocked(user_id=alice.user_id)
    assert [u.user_id for u in blocked] == [bob.user_id]
    await svc.unblock_user(user_id=alice.user_id, target_id=bob.user_id)
    assert await svc.list_blocked(user_id=alice.user_id) == []


# --- directory settings ---


async def test_directory_defaults_when_missing():
    svc, users, *_ = _make()
    alice = users.add("alice")
    view = await svc.get_directory_settings(user_id=alice.user_id)
    assert view.discoverable is True
    assert view.who_can_dm == "anyone"


async def test_update_directory_partial_preserves_other_field():
    svc, users, *_ = _make()
    alice = users.add("alice")
    await svc.update_directory_settings(user_id=alice.user_id, discoverable=False)
    view = await svc.update_directory_settings(user_id=alice.user_id, who_can_dm="contacts")
    assert view.discoverable is False  # untouched by the second patch
    assert view.who_can_dm == "contacts"


# --- auto-join (内测全员群) + group members ---


async def test_join_auto_join_chats_enrolls_pinned():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(title="内测群", auto_join=True)
    await svc.join_auto_join_chats(user_id=alice.user_id)
    member = await chats.get_member(group.id, alice.user_id)
    assert member is not None
    assert member.state == "accepted"
    assert member.pinned is True
    # The group now shows up in the user's chat list.
    views = await svc.list_chats(user_id=alice.user_id)
    assert [v.chat.id for v in views] == [group.id]


async def test_join_auto_join_is_idempotent():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(auto_join=True)
    await svc.join_auto_join_chats(user_id=alice.user_id)
    await svc.join_auto_join_chats(user_id=alice.user_id)
    members = [m for m in await chats.list_members(group.id) if m.user_id == alice.user_id]
    assert len(members) == 1


async def test_join_auto_join_skips_non_auto_chats():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    regular = await chats.create_group(auto_join=False)
    await svc.join_auto_join_chats(user_id=alice.user_id)
    assert await chats.get_member(regular.id, alice.user_id) is None


async def test_list_members_returns_participants():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    group = await chats.create_group(auto_join=True, member_ids=[alice.user_id, bob.user_id])
    members = await svc.list_members(chat_id=group.id, user_id=alice.user_id)
    assert {m.user.user_id for m in members} == {alice.user_id, bob.user_id}


async def test_list_members_non_member_404():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    stranger = users.add("stranger")
    group = await chats.create_group(auto_join=True, member_ids=[alice.user_id])
    with pytest.raises(NotFoundError):
        await svc.list_members(chat_id=group.id, user_id=stranger.user_id)


# --- leave_chat / set_chat_flags (群自助管理) ---


async def test_leave_chat_removes_member():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    group = await chats.create_group(auto_join=True, member_ids=[alice.user_id, bob.user_id])
    await svc.leave_chat(chat_id=group.id, user_id=alice.user_id)
    assert await chats.get_member(group.id, alice.user_id) is None
    # bob is untouched; the group lives on.
    assert await chats.get_member(group.id, bob.user_id) is not None
    # alice no longer sees it in her list.
    assert await svc.list_chats(user_id=alice.user_id) == []


async def test_leave_chat_non_member_404():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    stranger = users.add("stranger")
    group = await chats.create_group(auto_join=True, member_ids=[alice.user_id])
    with pytest.raises(NotFoundError):
        await svc.leave_chat(chat_id=group.id, user_id=stranger.user_id)


async def test_leave_chat_dm_rejected():
    svc, users, *_ = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    with pytest.raises(ValidationError):
        await svc.leave_chat(chat_id=chat.id, user_id=alice.user_id)


async def test_set_chat_flags_updates_and_returns_view():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(auto_join=True, member_ids=[alice.user_id])
    view = await svc.set_chat_flags(
        chat_id=group.id, user_id=alice.user_id, muted=True, pinned=True
    )
    assert view.member.muted is True
    assert view.member.pinned is True
    assert view.chat.id == group.id
    # group view resolves no dm peer
    assert view.peer is None


async def test_set_chat_flags_partial_preserves_other():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(auto_join=True, member_ids=[alice.user_id])
    await svc.set_chat_flags(chat_id=group.id, user_id=alice.user_id, pinned=True)
    view = await svc.set_chat_flags(chat_id=group.id, user_id=alice.user_id, muted=True)
    assert view.member.pinned is True  # untouched by the second patch
    assert view.member.muted is True


async def test_set_chat_flags_non_member_404():
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    stranger = users.add("stranger")
    group = await chats.create_group(auto_join=True, member_ids=[alice.user_id])
    with pytest.raises(NotFoundError):
        await svc.set_chat_flags(chat_id=group.id, user_id=stranger.user_id, muted=True)


# --- moderation: kick / mute / announce (Stage 3 审核治理) ---


async def test_kick_member_removes_and_posts_system_card():
    svc, users, chats, _blocks, _directory, events = _make()
    admin = users.add("admin", role="admin")
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[admin.user_id, alice.user_id])
    await svc.kick_member(chat_id=group.id, actor_id=admin.user_id, target_id=alice.user_id)
    assert await chats.get_member(group.id, alice.user_id) is None
    # the admin remains; the group lives on
    assert await chats.get_member(group.id, admin.user_id) is not None
    # a system_card notice (NULL sender) was fanned out to the remaining members
    recipients, event = events.published[-1]
    assert recipients == [admin.user_id]
    assert event["message"]["content_type"] == "system_card"
    assert event["message"]["sender_user_id"] is None
    assert "alice" in event["message"]["content"]


async def test_kick_admin_target_forbidden():
    svc, users, chats, *_ = _make()
    admin = users.add("admin", role="admin")
    other_admin = users.add("root", role="admin")
    group = await chats.create_group(member_ids=[admin.user_id, other_admin.user_id])
    with pytest.raises(AuthorizationError):
        await svc.kick_member(
            chat_id=group.id, actor_id=admin.user_id, target_id=other_admin.user_id
        )
    # the admin target is untouched
    assert await chats.get_member(group.id, other_admin.user_id) is not None


async def test_kick_non_member_404():
    svc, users, chats, *_ = _make()
    admin = users.add("admin", role="admin")
    stranger = users.add("stranger")
    group = await chats.create_group(member_ids=[admin.user_id])
    with pytest.raises(NotFoundError):
        await svc.kick_member(chat_id=group.id, actor_id=admin.user_id, target_id=stranger.user_id)


async def test_kick_dm_rejected():
    svc, users, *_ = _make()
    admin = users.add("admin", role="admin")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=admin.user_id, peer_id=bob.user_id)).chat
    with pytest.raises(ValidationError):
        await svc.kick_member(chat_id=chat.id, actor_id=admin.user_id, target_id=bob.user_id)


async def test_admin_mute_blocks_send_then_unmute_restores():
    svc, users, chats, *_ = _make()
    admin = users.add("admin", role="admin")
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[admin.user_id, alice.user_id])
    await svc.set_admin_mute(
        chat_id=group.id, actor_id=admin.user_id, target_id=alice.user_id, muted=True
    )
    with pytest.raises(AuthorizationError):
        await svc.send_message(chat_id=group.id, sender_id=alice.user_id, content="hi")
    # unmuting restores the ability to send
    await svc.set_admin_mute(
        chat_id=group.id, actor_id=admin.user_id, target_id=alice.user_id, muted=False
    )
    msg = await svc.send_message(chat_id=group.id, sender_id=alice.user_id, content="hi again")
    assert msg.content == "hi again"


async def test_admin_mute_reflected_in_roster():
    svc, users, chats, *_ = _make()
    admin = users.add("admin", role="admin")
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[admin.user_id, alice.user_id])
    await svc.set_admin_mute(
        chat_id=group.id, actor_id=admin.user_id, target_id=alice.user_id, muted=True
    )
    members = await svc.list_members(chat_id=group.id, user_id=admin.user_id)
    by_id = {m.user.user_id: m for m in members}
    assert by_id[admin.user_id].is_admin is True
    assert by_id[alice.user_id].is_admin is False
    assert by_id[alice.user_id].muted_by_admin is True
    assert by_id[admin.user_id].muted_by_admin is False


async def test_announce_posts_system_card_to_all_members():
    svc, users, chats, _blocks, _directory, events = _make()
    admin = users.add("admin", role="admin")
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[admin.user_id, alice.user_id])
    msg = await svc.post_announcement(chat_id=group.id, actor_id=admin.user_id, content="维护通知")
    assert msg.content_type == "system_card"
    assert msg.sender_user_id is None
    recipients, event = events.published[-1]
    assert set(recipients) == {admin.user_id, alice.user_id}
    assert event["message"]["content"] == "维护通知"


async def test_announce_dm_rejected():
    svc, users, *_ = _make()
    admin = users.add("admin", role="admin")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=admin.user_id, peer_id=bob.user_id)).chat
    with pytest.raises(ValidationError):
        await svc.post_announcement(chat_id=chat.id, actor_id=admin.user_id, content="hi")


# --- attachments: upload / download (Stage 4 富消息) ---
# These touch the real filesystem (build_chat_workspace), so data_dir is redirected
# to tmp_path; the repos stay in-memory fakes for the membership gate.


def _png_bytes(width: int, height: int) -> bytes:
    """A real PNG of the given size, for the thumbnail/upload tests."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (120, 30, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_upload_attachment_roundtrips(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[alice.user_id])
    result = await svc.upload_attachment(
        chat_id=group.id,
        user_id=alice.user_id,
        path="attachments/x/pic.png",
        data=b"\x89PNG\r\n",
    )
    assert result.size_bytes == 6
    # non-image bytes → no thumbnail (the original is served inline)
    assert result.thumb_path is None
    # the bytes land under the chat's own im/<chat_id> space
    stored = tmp_path / "workspaces" / "im" / group.id / "attachments" / "x" / "pic.png"
    assert stored.read_bytes() == b"\x89PNG\r\n"
    # and a member can read them back byte-for-byte
    got = await svc.download_attachment(
        chat_id=group.id, user_id=alice.user_id, path="attachments/x/pic.png"
    )
    assert got == b"\x89PNG\r\n"


async def test_upload_image_generates_bounded_webp_thumbnail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[alice.user_id])
    data = _png_bytes(1000, 800)
    result = await svc.upload_attachment(
        chat_id=group.id, user_id=alice.user_id, path="attachments/x/photo.png", data=data
    )
    # a sibling thumbnail path is returned and a member can fetch it
    assert result.thumb_path == "attachments/x/photo.png.thumb.webp"
    thumb = await svc.download_attachment(
        chat_id=group.id, user_id=alice.user_id, path=result.thumb_path
    )
    import io

    from PIL import Image

    with Image.open(io.BytesIO(thumb)) as img:
        assert img.format == "WEBP"
        assert max(img.size) <= 512  # bounded to the longest-edge cap


async def test_upload_small_image_skips_thumbnail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[alice.user_id])
    result = await svc.upload_attachment(
        chat_id=group.id,
        user_id=alice.user_id,
        path="attachments/y/small.png",
        data=_png_bytes(100, 80),
    )
    # already within the cap → no thumbnail (it would save nothing)
    assert result.thumb_path is None


async def test_upload_attachment_non_member_404(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    stranger = users.add("stranger")
    group = await chats.create_group(member_ids=[alice.user_id])
    with pytest.raises(NotFoundError):
        await svc.upload_attachment(
            chat_id=group.id, user_id=stranger.user_id, path="attachments/a", data=b"x"
        )


async def test_download_attachment_non_member_404(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    stranger = users.add("stranger")
    group = await chats.create_group(member_ids=[alice.user_id])
    await svc.upload_attachment(
        chat_id=group.id, user_id=alice.user_id, path="attachments/a", data=b"x"
    )
    with pytest.raises(NotFoundError):
        await svc.download_attachment(
            chat_id=group.id, user_id=stranger.user_id, path="attachments/a"
        )


async def test_download_attachment_missing_404(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[alice.user_id])
    with pytest.raises(NotFoundError):
        await svc.download_attachment(
            chat_id=group.id, user_id=alice.user_id, path="attachments/missing.png"
        )


async def test_upload_attachment_traversal_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, chats, *_ = _make()
    alice = users.add("alice")
    group = await chats.create_group(member_ids=[alice.user_id])
    with pytest.raises(ValidationError):
        await svc.upload_attachment(
            chat_id=group.id,
            user_id=alice.user_id,
            path="../../escape.txt",
            data=b"x",
        )


async def test_send_message_attachments_only_no_content(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    svc, users, _chats, _blocks, _directory, events = _make()
    alice = users.add("alice")
    bob = users.add("bob")
    chat = (await svc.start_dm(requester_id=alice.user_id, peer_id=bob.user_id)).chat
    att = [{"name": "pic.png", "path": "pic.png", "workspace_path": "attachments/x/pic.png"}]
    msg = await svc.send_message(
        chat_id=chat.id,
        sender_id=alice.user_id,
        content=None,
        content_type="image",
        attachments=att,
    )
    assert msg.content is None
    assert msg.content_type == "image"
    assert msg.attachments == att
    # the realtime fan-out carries the attachments + content_type
    _recipients, event = events.published[-1]
    assert event["message"]["content_type"] == "image"
    assert event["message"]["attachments"] == att
