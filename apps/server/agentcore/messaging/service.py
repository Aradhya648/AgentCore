"""Messaging service: the 消息 page (找人 IM) business logic (消息IM.md).

Holds all IM policy so the HTTP layer stays thin and the repos do pure data
access:
- 任意搜人 visibility: exact-match search, minus self, blocked pairs, and users
  who opted out of discovery (``user_directory_settings.discoverable``);
- who-can-DM gate: opening a *new* dm with someone set to ``contacts`` is refused
  (no contact graph in P0 → effectively a hard opt-out), while the default
  ``anyone`` lets a stranger through as a *message request* (peer starts pending);
- send-message guards: must be a chat member (else 404, IDOR-safe), dm blocked
  pairs are refused, and a reply by the requested party clears their pending gate;
- list / unread / read-cursor / block / directory-settings management.

The service depends on repository instances (unit-testable with in-memory fakes)
and an optional realtime publisher (a seam — see ``events.py``) it calls to fan a
new message out to every member's live connections.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agentcore.core.errors import (
    AuthorizationError,
    NotFoundError,
    ValidationError,
)
from agentcore.core.logging import get_logger
from agentcore.db.models import Chat, ChatMember, ChatMessage, User
from agentcore.db.repositories import (
    ChatRepository,
    UserBlockRepository,
    UserDirectoryRepository,
    UserRepository,
)
from agentcore.messaging.events import ChatEventPublisher, NullChatEventPublisher
from agentcore.messaging.thumbnails import make_image_thumbnail
from agentcore.workspace.locate import build_chat_workspace
from agentcore.workspace.protocol import (
    NotAFile,
    OutsideWorkspace,
    PathNotFound,
    WorkspaceError,
    WorkspaceIOError,
)

logger = get_logger(__name__)

_MAX_PAGE_SIZE = 100
_DEFAULT_PAGE_SIZE = 50
# Reply-quote body preview: keep short for bubble quote bars.
_REPLY_PREVIEW_MAX = 100
_OFFICIAL_DISPLAY_NAME = "官方号"
_ATTACHMENT_PREVIEW_LABELS = {
    "image": "[图片]",
    "file": "[文件]",
    "system_card": "[系统消息]",
}


@dataclass(frozen=True)
class ChatView:
    """A chat plus the viewer's per-chat state and resolved dm peer — the domain
    shape the route maps to ``ChatSummary`` (schema conversion stays in the route).
    """

    chat: Chat
    member: ChatMember
    peer: User | None
    unread: int


@dataclass(frozen=True)
class DirectoryView:
    """A user's resolved discoverability + who-can-DM (defaults applied)."""

    discoverable: bool
    who_can_dm: str


@dataclass(frozen=True)
class MessagePage:
    """A page of chat messages with paging echoed back for the list response."""

    messages: Sequence[ChatMessage]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class AttachmentUpload:
    """The result of storing an attachment: bytes written + the optional thumbnail.

    ``thumb_path`` is a workspace-relative path to a generated WebP preview for
    images (None for non-images / small images / a failed thumbnail), referenced
    by the message's ``StoredAttachment`` so the bubble can inline it cheaply.
    """

    size_bytes: int
    thumb_path: str | None


@dataclass(frozen=True)
class MemberView:
    """A group member for the roster: their user plus moderation-relevant flags.

    ``is_admin`` mirrors the platform role (创始团队 = 平台 admin, the 内测群's
    moderators) so the client can badge official accounts and hide kick/mute on
    them; ``muted_by_admin`` surfaces the admin-imposed 禁言 state.
    """

    user: User
    is_admin: bool
    muted_by_admin: bool


class MessagingService:
    def __init__(
        self,
        *,
        users: UserRepository,
        chats: ChatRepository,
        blocks: UserBlockRepository,
        directory: UserDirectoryRepository,
        events: ChatEventPublisher | None = None,
        shared_spaces: Any | None = None,
    ) -> None:
        self._users = users
        self._chats = chats
        self._blocks = blocks
        self._directory = directory
        self._events: ChatEventPublisher = events or NullChatEventPublisher()
        # Optional SharedSpaceRepository — when set, blocking auto-rejects
        # pending shared-space invites between the pair (D3); does not kick members.
        self._shared_spaces = shared_spaces

    # --- People search (任意搜人 + 护栏) ---

    async def search_users(self, *, requester_id: str, query: str, limit: int = 20) -> list[User]:
        """Exact-match people-search, filtered by visibility rules.

        Drops the requester themselves, any user in a block relationship with
        them (either direction), and anyone who turned discovery off. A missing
        directory row means discoverable (open search is the product default).
        """
        candidates = await self._users.search(query, limit=limit)
        visible: list[User] = []
        for user in candidates:
            if user.user_id == requester_id:
                continue
            if await self._blocks.is_blocked_between(requester_id, user.user_id):
                continue
            settings = await self._directory.get(user.user_id)
            if settings is not None and not settings.discoverable:
                continue
            visible.append(user)
        return visible

    # --- Chats ---

    async def start_dm(self, *, requester_id: str, peer_id: str) -> ChatView:
        """Open (or reuse) a 1:1 chat with another user.

        Reuses the existing dm if there is one (idempotent open). For a brand-new
        dm: refuses self-dm, unknown/disabled peers, blocked pairs, and peers set
        to ``who_can_dm = contacts``. The peer joins ``pending`` (message request)
        until they reply.
        """
        if peer_id == requester_id:
            raise ValidationError("不能与自己发起会话")
        peer = await self._users.get_by_id(peer_id)
        if peer is None or peer.status != "active":
            raise NotFoundError("用户不存在")
        if await self._blocks.is_blocked_between(requester_id, peer_id):
            raise AuthorizationError("无法向该用户发送消息")

        existing = await self._chats.get_dm(requester_id, peer_id)
        if existing is not None:
            member = await self._chats.get_member(existing.id, requester_id)
            assert member is not None  # creator is always a member of their dm
            return ChatView(chat=existing, member=member, peer=peer, unread=0)

        settings = await self._directory.get(peer_id)
        if settings is not None and settings.who_can_dm == "contacts":
            raise AuthorizationError("对方仅允许联系人发起会话")

        chat = await self._chats.create_dm(creator_id=requester_id, peer_id=peer_id)
        member = await self._chats.get_member(chat.id, requester_id)
        assert member is not None
        logger.debug("dm.opened", chat=chat.id, by=requester_id, peer=peer_id)
        return ChatView(chat=chat, member=member, peer=peer, unread=0)

    async def join_auto_join_chats(self, *, user_id: str) -> None:
        """Enroll a user into every auto-join chat (内测群 + official broadcast).

        Called once at registration. Idempotent per chat — a user already in a
        chat is left untouched (so re-running never resets their state). Pinned on
        join so the chat surfaces at the top of a brand-new user's list.
        """
        chats = await self._chats.list_auto_join_chats()
        for chat in chats:
            await self._chats.add_member(chat.id, user_id, pinned=True)
        if chats:
            logger.info("chat.auto_join", user=user_id, chats=[c.id for c in chats])

    async def ensure_official_membership(self, *, user_id: str) -> None:
        """Idempotent enrollment into the official broadcast chat.

        Leave is forbidden on the official chat, so login / list-chats may call
        this as a兜底 for accounts that missed registration auto-join (e.g.
        created before the official chat migration). Does **not** re-enroll
        leavers of the 内测群 (that chat remains registration-only). No-ops when
        the official chat row is absent (pre-migration).
        """
        chat = await self._chats.get_official_chat()
        if chat is None:
            return
        if await self._chats.get_member(chat.id, user_id) is not None:
            return
        await self._chats.add_member(chat.id, user_id, pinned=True)
        logger.info("chat.auto_join", user=user_id, chats=[chat.id])

    async def list_members(self, *, chat_id: str, user_id: str) -> list[MemberView]:
        """The members of a chat (for the group roster + member panel).

        Non-members get 404 (IDOR-safe). Returns members in join order, each with
        their platform-admin and admin-mute flags so the route can build a
        ``ChatParticipant``. Members whose account no longer resolves are dropped.
        """
        if await self._chats.get_member(chat_id, user_id) is None:
            raise NotFoundError("会话不存在")
        members = sorted(await self._chats.list_members(chat_id), key=lambda m: m.joined_at)
        users = await self._users.get_by_ids([m.user_id for m in members])
        views: list[MemberView] = []
        for m in members:
            user = users.get(m.user_id)
            if user is None:
                continue
            views.append(
                MemberView(
                    user=user,
                    is_admin=user.role == "admin",
                    muted_by_admin=m.muted_by_admin,
                )
            )
        return views

    async def leave_chat(self, *, chat_id: str, user_id: str) -> None:
        """Leave a group chat (removes this user's membership).

        Non-members 404. Dms can't be "left" (they're a pair, not a room). The
        official broadcast chat also refuses leave (422) — membership is
        mandatory and list/login兜底 would re-enroll anyway. Auto-join for the
        内测群 fires only at registration, so leaving that group sticks.
        """
        member = await self._chats.get_member(chat_id, user_id)
        if member is None:
            raise NotFoundError("会话不存在")
        chat = await self._chats.get_chat(chat_id)
        if chat is not None and chat.type == "dm":
            raise ValidationError("单聊不支持退出")
        if chat is not None and chat.type == "official":
            raise ValidationError("官方号不支持退出")
        await self._chats.remove_member(chat_id, user_id)
        logger.info("chat.left", chat=chat_id, user=user_id)

    async def set_chat_flags(
        self,
        *,
        chat_id: str,
        user_id: str,
        muted: bool | None = None,
        pinned: bool | None = None,
    ) -> ChatView:
        """Update this user's per-chat flags (mute / pin) and return the row."""
        if await self._chats.get_member(chat_id, user_id) is None:
            raise NotFoundError("会话不存在")
        await self._chats.set_membership_flags(chat_id, user_id, muted=muted, pinned=pinned)
        return await self.chat_view(chat_id=chat_id, user_id=user_id)

    # --- Moderation (Stage 3 审核治理: 平台 admin kick / mute / announce) ---
    # Platform-admin authority is gated at the route (``AdminUser``); these methods
    # own the resource invariants (chat is a moderated group, target is a member,
    # admins can't be moderated) and the system-card side effects.

    async def kick_member(self, *, chat_id: str, actor_id: str, target_id: str) -> None:
        """Remove a member from a group (admin 踢人) and post a system notice.

        404 unknown chat / target-not-a-member; 422 for a dm (a pair, not a room);
        403 when the target is a platform admin (admins can't be moderated — no
        civil war / self-lockout). The kicked user is dropped, then a centered
        ``system_card`` is fanned out to the remaining members.
        """
        await self._require_moderatable_group(chat_id)
        await self._assert_target_moderatable(chat_id, target_id)
        target = await self._users.get_by_id(target_id)
        await self._chats.remove_member(chat_id, target_id)
        name = target.display_name if target else "成员"
        await self._post_system_card(
            chat_id=chat_id,
            content=f"{name} 已被移出群聊",
            payload={"kind": "member_removed", "user_id": target_id},
        )
        logger.info("chat.kicked", chat=chat_id, by=actor_id, target=target_id)

    async def set_admin_mute(
        self, *, chat_id: str, actor_id: str, target_id: str, muted: bool
    ) -> None:
        """Mute / unmute a member (admin 禁言): a muted member keeps reading but a
        send is refused (403, in :meth:`send_message`).

        Same gates as :meth:`kick_member`. No全群 broadcast — 禁言 is targeted, not
        announced (Stage 3 decision); the member learns of it when a send is
        refused, and the roster shows the state to admins.
        """
        await self._require_moderatable_group(chat_id)
        await self._assert_target_moderatable(chat_id, target_id)
        await self._chats.set_admin_mute(chat_id, target_id, muted_by_admin=muted)
        logger.info(
            "chat.admin_mute",
            chat=chat_id,
            by=actor_id,
            target=target_id,
            muted=muted,
        )

    async def post_announcement(self, *, chat_id: str, actor_id: str, content: str) -> ChatMessage:
        """Post an admin announcement (官方公告) as a centered ``system_card``.

        Sent as the official/system account (NULL sender) so it renders as a
        notice rather than a normal bubble, and fanned out to every member. 404
        unknown chat; 422 for a dm.
        """
        await self._require_moderatable_group(chat_id)
        message = await self._post_system_card(
            chat_id=chat_id,
            content=content,
            payload={"kind": "announcement", "by": actor_id},
        )
        logger.info("chat.announced", chat=chat_id, by=actor_id)
        return message

    async def publish_product_notice(
        self,
        *,
        notice_id: str,
        title: str,
        body: str,
        severity: str,
        surface: str,
        cta_label: str | None = None,
        cta_url: str | None = None,
    ) -> ChatMessage | None:
        """Mirror a published product Notice into the official broadcast chat.

        Only ``surface ∈ {inbox, both}`` writes an IM message (banner-only stays
        on the Notice surfaces). One shared ``system_card`` for all members —
        never per-user copies. Returns ``None`` when the surface skips IM.
        """
        if surface not in ("inbox", "both"):
            return None
        chat = await self._chats.get_or_create_official_chat()
        payload: dict[str, Any] = {
            "kind": "product_notice",
            "notice_id": notice_id,
            "severity": severity,
        }
        if cta_label:
            payload["cta_label"] = cta_label
        if cta_url:
            payload["cta_url"] = cta_url
        content = f"{title}\n{body}".strip() if body else title
        message = await self._post_system_card(
            chat_id=chat.id,
            content=content,
            payload=payload,
        )
        logger.info(
            "chat.product_notice_published",
            chat=chat.id,
            notice_id=notice_id,
            surface=surface,
        )
        return message

    async def _require_moderatable_group(self, chat_id: str) -> Chat:
        """Resolve a chat that supports moderation (group/official, not a dm)."""
        chat = await self._chats.get_chat(chat_id)
        if chat is None:
            raise NotFoundError("会话不存在")
        if chat.type == "dm":
            raise ValidationError("单聊不支持该操作")
        return chat

    async def _assert_target_moderatable(self, chat_id: str, target_id: str) -> None:
        """Guard a kick/mute target: must be a current member and not an admin.

        Admins are exempt from moderation so creators can't kick/mute each other
        (or themselves) out of the 内测群.
        """
        if await self._chats.get_member(chat_id, target_id) is None:
            raise NotFoundError("该用户不在群内")
        target = await self._users.get_by_id(target_id)
        if target is not None and target.role == "admin":
            raise AuthorizationError("不能对管理员执行该操作")

    async def _post_system_card(
        self, *, chat_id: str, content: str, payload: dict[str, Any] | None = None
    ) -> ChatMessage:
        """Append a ``system_card`` (NULL sender = official) and fan it out to the
        chat's current members. Shared by kick notices and announcements.
        """
        message = await self._chats.add_message(
            chat_id=chat_id,
            sender_user_id=None,
            content=content,
            sender_type="official",
            content_type="system_card",
            payload=payload,
        )
        members = await self._chats.list_members(chat_id)
        await self._events.publish([m.user_id for m in members], self._message_event(message))
        return message

    async def chat_view(self, *, chat_id: str, user_id: str) -> ChatView:
        """Build one chat's view (chat + this user's state + dm peer + unread).

        Single-chat counterpart to :meth:`list_chats` for endpoints that return
        one updated row (e.g. a flags patch). Non-members 404.
        """
        chat = await self._chats.get_chat(chat_id)
        member = await self._chats.get_member(chat_id, user_id)
        if chat is None or member is None:
            raise NotFoundError("会话不存在")
        peer: User | None = None
        if chat.type == "dm":
            peer_ids = await self._chats.peer_ids_for([chat_id], exclude_user_id=user_id)
            peer_id = peer_ids.get(chat_id)
            if peer_id:
                peer = (await self._users.get_by_ids([peer_id])).get(peer_id)
        unread = (await self._chats.unread_counts(user_id)).get(chat_id, 0)
        return ChatView(chat=chat, member=member, peer=peer, unread=unread)

    async def list_chats(self, *, user_id: str) -> list[ChatView]:
        """The user's chat list (pinned first, then recent), with unread counts and
        dm peers resolved in batch (no N+1).

        Ensures official-chat membership before listing (兜底 for accounts that
        missed registration auto-join after the official chat was introduced).
        """
        await self.ensure_official_membership(user_id=user_id)
        memberships = await self._chats.list_memberships(user_id)
        # Resolve "the other human" only for dms — a group/official chat has no
        # single peer (the client renders its title), and picking an arbitrary
        # member would leak that member as the row's identity.
        dm_ids = [chat.id for chat, _ in memberships if chat.type == "dm"]
        unread = await self._chats.unread_counts(user_id)
        peer_ids = await self._chats.peer_ids_for(dm_ids, exclude_user_id=user_id)
        peers = await self._users.get_by_ids(list(peer_ids.values()))

        views: list[ChatView] = []
        for chat, member in memberships:
            peer_id = peer_ids.get(chat.id)
            peer = peers.get(peer_id) if peer_id else None
            views.append(
                ChatView(
                    chat=chat,
                    member=member,
                    peer=peer,
                    unread=unread.get(chat.id, 0),
                )
            )
        return views

    # --- Messages ---

    async def send_message(
        self,
        *,
        chat_id: str,
        sender_id: str,
        content: str | None,
        content_type: str = "text",
        attachments: list | None = None,
        reply_to_message_id: str | None = None,
        mentions: list[dict[str, Any]] | None = None,
        client_msg_id: str | None = None,
    ) -> ChatMessage:
        """Send a message into a chat the user belongs to.

        Non-members get 404 (IDOR-safe — no existence leak). Users cannot send
        into the official broadcast chat (422 — read-only fan-in). In a dm, a
        block in either direction refuses the send. A reply by the party who was
        holding a pending message-request accepts it. The stored message is
        fanned out to every member's live connections (sender included, for
        multi-device). ``content`` may be empty for a 富消息 carrying only
        ``attachments``. Structured ``mentions`` are validated and frozen onto
        the row (accepted members only; ``@所有人`` = group + platform admin).
        """
        member = await self._chats.get_member(chat_id, sender_id)
        if member is None:
            raise NotFoundError("会话不存在")
        chat = await self._chats.get_chat(chat_id)
        if chat is None:
            raise NotFoundError("会话不存在")
        if chat.type == "official":
            raise ValidationError("官方号不支持发送消息")
        if member.muted_by_admin:
            raise AuthorizationError("你已被管理员禁言，暂时无法发言")

        if chat.type == "dm":
            peer_ids = await self._chats.peer_ids_for([chat_id], exclude_user_id=sender_id)
            peer_id = peer_ids.get(chat_id)
            if peer_id and await self._blocks.is_blocked_between(sender_id, peer_id):
                raise AuthorizationError("无法向该用户发送消息")

        reply_id, reply_snapshot = await self._resolve_reply_to(
            chat_id=chat_id, reply_to_message_id=reply_to_message_id
        )
        frozen_mentions = await self._resolve_mentions(
            chat=chat, sender_id=sender_id, mentions=mentions
        )

        message = await self._chats.add_message(
            chat_id=chat_id,
            sender_user_id=sender_id,
            content=content,
            content_type=content_type,
            attachments=attachments,
            reply_to_message_id=reply_id,
            reply_to=reply_snapshot,
            mentions=frozen_mentions,
            client_msg_id=client_msg_id,
        )

        if member.state == "pending":
            await self._chats.accept_request(chat_id, sender_id)

        members = await self._chats.list_members(chat_id)
        await self._events.publish([m.user_id for m in members], self._message_event(message))
        return message

    async def _resolve_reply_to(
        self, *, chat_id: str, reply_to_message_id: str | None
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Validate ``reply_to_message_id`` and freeze a lightweight quote snapshot.

        Target must exist and share ``chat_id`` (else 422). Snapshot is written onto
        the new message so a later recall of the target still leaves a readable quote.
        """
        if not reply_to_message_id:
            return None, None
        target = await self._chats.get_message(reply_to_message_id)
        if target is None or target.chat_id != chat_id:
            raise ValidationError("回复的消息不存在或不属于当前会话")
        display_name = _OFFICIAL_DISPLAY_NAME
        if target.sender_user_id:
            user = await self._users.get_by_id(target.sender_user_id)
            display_name = (
                (user.display_name if user and user.display_name else None)
                or (user.username if user else None)
                or "用户"
            )
        return reply_to_message_id, {
            "sender_user_id": target.sender_user_id,
            "sender_display_name": display_name,
            "body_preview": self._body_preview(target),
        }

    async def _resolve_mentions(
        self,
        *,
        chat: Chat,
        sender_id: str,
        mentions: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Validate and freeze structured mentions (deduped; source of truth).

        ``kind=user``: ``user_id`` must be an *accepted* member of this chat (422).
        ``kind=everyone``: group only (422 on dm); caller must be platform admin
        (``users.role == 'admin'``) else 403. Same rule for 内测全员群 and other groups.
        """
        if not mentions:
            return []

        members = await self._chats.list_members(chat.id)
        accepted_ids = {m.user_id for m in members if m.state == "accepted"}

        frozen: list[dict[str, Any]] = []
        seen_users: set[str] = set()
        saw_everyone = False

        for raw in mentions:
            kind = raw.get("kind") if isinstance(raw, dict) else None
            if kind == "user":
                user_id = raw.get("user_id")
                if not isinstance(user_id, str) or not user_id:
                    raise ValidationError("@提及的用户无效")
                if user_id in seen_users:
                    continue
                if user_id not in accepted_ids:
                    raise ValidationError("@提及的用户不是本会话成员")
                seen_users.add(user_id)
                frozen.append({"kind": "user", "user_id": user_id})
            elif kind == "everyone":
                if saw_everyone:
                    continue
                if chat.type != "group":
                    raise ValidationError("单聊不支持@所有人")
                sender = await self._users.get_by_id(sender_id)
                if sender is None or getattr(sender, "role", None) != "admin":
                    raise AuthorizationError("仅平台管理员可@所有人")
                saw_everyone = True
                frozen.append({"kind": "everyone"})
            else:
                raise ValidationError("@提及类型无效")

        return frozen

    @staticmethod
    def _body_preview(message: ChatMessage) -> str:
        """Truncate body text, or fall back to an attachment-type label."""
        text = (message.content or "").strip()
        if text:
            return text[:_REPLY_PREVIEW_MAX]
        label = _ATTACHMENT_PREVIEW_LABELS.get(message.content_type)
        if label:
            return label
        attachments = message.attachments or []
        if attachments:
            # Prefer image label when any attachment carries a thumbnail.
            if any(
                isinstance(a, dict) and a.get("thumb_path") for a in attachments
            ):
                return "[图片]"
            return "[文件]"
        return ""

    # --- Attachments (富消息: 图/文件，复用工作区存储) ---
    # A chat owns a shared ``ServerWorkspace`` (build_chat_workspace) under
    # ``workspaces/im/<chat_id>/``. Upload then send is two steps: PUT the bytes
    # here, then reference the returned path in a send_message attachment. Both
    # gate membership first (non-member 404), and the chat-scoped backend means a
    # member can only reach this chat's files — never another chat's (no IDOR).

    async def upload_attachment(
        self, *, chat_id: str, user_id: str, path: str, data: bytes
    ) -> AttachmentUpload:
        """Store an attachment's bytes in the chat's workspace; return its metadata.

        Members only (404 otherwise). ``path`` is workspace-relative; one escaping
        the chat space is refused (422). Size limits are enforced at the route
        before the body is read.

        For an image, a bounded WebP thumbnail is generated and stored alongside
        (``<path>.thumb.webp``) so the thread can show cheap inline previews; its
        path rides back in ``thumb_path``. Thumbnailing is best-effort and off the
        event loop (CPU-bound) — a failure leaves ``thumb_path`` None and the
        original is served inline.
        """
        if await self._chats.get_member(chat_id, user_id) is None:
            raise NotFoundError("会话不存在")
        chat = await self._chats.get_chat(chat_id)
        if chat is not None and chat.type == "official":
            raise ValidationError("官方号不支持发送消息")
        backend = build_chat_workspace(chat_id)
        try:
            size_bytes = await backend.write_bytes(path, data)
        except OutsideWorkspace as e:
            raise ValidationError("路径非法：超出会话附件范围") from e
        except WorkspaceIOError as e:
            raise ValidationError(f"附件写入失败：{e}") from e

        thumb_path: str | None = None
        thumbnail = await asyncio.to_thread(make_image_thumbnail, data)
        if thumbnail is not None:
            candidate = f"{path}.thumb.webp"
            try:
                await backend.write_bytes(candidate, thumbnail)
                thumb_path = candidate
            except WorkspaceError as e:
                # The original is already stored and serviceable; a missing
                # thumbnail just means the client inlines the full image.
                logger.warning("chat.thumbnail_store_failed", chat=chat_id, error=str(e))
        return AttachmentUpload(size_bytes=size_bytes, thumb_path=thumb_path)

    async def download_attachment(self, *, chat_id: str, user_id: str, path: str) -> bytes:
        """Return an attachment's raw bytes (members only; 404 otherwise).

        Scoped to this chat's workspace, so a member can fetch only files that
        belong to this chat. 404 for a missing path; 422 for an illegal path.
        """
        if await self._chats.get_member(chat_id, user_id) is None:
            raise NotFoundError("会话不存在")
        backend = build_chat_workspace(chat_id)
        try:
            return await backend.read_bytes(path)
        except OutsideWorkspace as e:
            raise ValidationError("路径非法：超出会话附件范围") from e
        except (PathNotFound, NotAFile) as e:
            raise NotFoundError("附件不存在") from e

    async def list_messages(
        self,
        *,
        chat_id: str,
        user_id: str,
        page: int = 1,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> MessagePage:
        """A page of a chat's messages (oldest first). Non-members get 404."""
        if await self._chats.get_member(chat_id, user_id) is None:
            raise NotFoundError("会话不存在")
        page = max(1, page)
        page_size = max(1, min(page_size, _MAX_PAGE_SIZE))
        offset = (page - 1) * page_size
        messages, total = await self._chats.list_messages(chat_id, limit=page_size, offset=offset)
        return MessagePage(messages=messages, total=total, page=page, page_size=page_size)

    async def mark_read(self, *, chat_id: str, user_id: str, last_read_message_id: str) -> None:
        """Advance the user's read cursor (drives unread counts). Non-members 404."""
        if await self._chats.get_member(chat_id, user_id) is None:
            raise NotFoundError("会话不存在")
        await self._chats.mark_read(chat_id, user_id, last_read_message_id=last_read_message_id)

    # --- Blocking (任意搜人 护栏) ---

    async def block_user(self, *, user_id: str, target_id: str) -> None:
        if target_id == user_id:
            raise ValidationError("不能拉黑自己")
        target = await self._users.get_by_id(target_id)
        if target is None:
            raise NotFoundError("用户不存在")
        await self._blocks.block(user_id, target_id)
        if self._shared_spaces is not None:
            await self._shared_spaces.delete_pending_between(user_id, target_id)
        logger.info("dm.user_blocked", user=user_id, target=target_id)

    async def unblock_user(self, *, user_id: str, target_id: str) -> None:
        await self._blocks.unblock(user_id, target_id)

    async def list_blocked(self, *, user_id: str) -> list[User]:
        blocked_ids = await self._blocks.list_blocked(user_id)
        users = await self._users.get_by_ids(blocked_ids)
        return [users[uid] for uid in blocked_ids if uid in users]

    # --- Directory settings (discoverability + who-can-DM) ---

    async def get_directory_settings(self, *, user_id: str) -> DirectoryView:
        settings = await self._directory.get(user_id)
        if settings is None:
            return DirectoryView(discoverable=True, who_can_dm="anyone")
        return DirectoryView(discoverable=settings.discoverable, who_can_dm=settings.who_can_dm)

    async def update_directory_settings(
        self,
        *,
        user_id: str,
        discoverable: bool | None = None,
        who_can_dm: str | None = None,
    ) -> DirectoryView:
        """Patch the user's privacy settings; ``None`` leaves a field unchanged."""
        changes: dict[str, Any] = {}
        if discoverable is not None:
            changes["discoverable"] = discoverable
        if who_can_dm is not None:
            changes["who_can_dm"] = who_can_dm
        settings = await self._directory.upsert(user_id, **changes)
        return DirectoryView(discoverable=settings.discoverable, who_can_dm=settings.who_can_dm)

    # --- Realtime event payloads ---

    @staticmethod
    def _message_event(message: ChatMessage) -> dict[str, Any]:
        """The ``chat_message`` realtime event (mirrors ``ChatMessageDetail``)."""
        return {
            "type": "chat_message",
            "chat_id": message.chat_id,
            "message": {
                "id": message.id,
                "chat_id": message.chat_id,
                "sender_user_id": message.sender_user_id,
                "sender_type": message.sender_type,
                "content": message.content,
                "content_type": message.content_type,
                "attachments": message.attachments or [],
                "payload": message.payload,
                "reply_to_message_id": message.reply_to_message_id,
                "reply_to": message.reply_to,
                "mentions": message.mentions or [],
                "created_at": (message.created_at.isoformat() if message.created_at else None),
            },
        }
