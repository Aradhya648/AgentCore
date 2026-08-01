"""消息 page (找人 IM) routes: people-search, dms, messages, read, blocks, privacy.

The 消息 page is "找人" (human↔human), a separate domain from the 对话 page's AI
conversations — see ``docs/05-平台与运维/消息IM.md``. Every route resolves the
authenticated user and scopes through ``MessagingService``: a non-member of a chat
gets 404 (IDOR-safe), block/discoverability/who-can-DM gates live in the service.
The service returns ORM/domain objects; this layer owns the Pydantic conversion
(notably ``User.user_id`` → the API's ``id``).
"""

import mimetypes

from fastapi import APIRouter, Depends, Query, Request, Response

from agentcore.api.dependencies import AdminUser, AuthUser, get_messaging_service
from agentcore.api.download_headers import download_headers
from agentcore.api.schemas import (
    AdminMuteRequest,
    AnnounceRequest,
    BlockedUser,
    BlockListResponse,
    BlockUserRequest,
    ChatFileUploadResponse,
    ChatListResponse,
    ChatMembersResponse,
    ChatMessageDetail,
    ChatMessageListResponse,
    ChatParticipant,
    ChatSummary,
    CreateFriendRequestBody,
    DirectorySettings,
    EditChatMessageRequest,
    FriendListResponse,
    FriendRequestDetail,
    FriendRequestListResponse,
    FriendSummary,
    MarkReadRequest,
    SendChatMessageRequest,
    StartDmRequest,
    StatusResponse,
    UpdateDirectorySettingsRequest,
    UpdateMembershipRequest,
    UserProfile,
    UserSearchResponse,
    UserSearchResult,
)
from agentcore.config import settings
from agentcore.conversation.rate_limit import enforce_user_message_rate_limit
from agentcore.core.errors import ValidationError
from agentcore.messaging import ChatView, DirectoryView, MessagingService, ProfileView
from agentcore.messaging.hub import default_chat_hub

router = APIRouter(prefix="/messages", tags=["messages"])


# --- ORM/domain → schema conversion (kept in the route, per repo convention) ---


def _participant(
    user,
    *,
    is_admin: bool = False,
    muted_by_admin: bool = False,
    online: bool = False,
) -> ChatParticipant:
    return ChatParticipant(
        id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        is_admin=is_admin,
        muted_by_admin=muted_by_admin,
        online=online,
    )


def _search_result(user) -> UserSearchResult:
    return UserSearchResult(id=user.user_id, username=user.username, display_name=user.display_name)


def _blocked_user(user) -> BlockedUser:
    return BlockedUser(id=user.user_id, username=user.username, display_name=user.display_name)


def _chat_summary(
    view: ChatView,
    *,
    online_ids: frozenset[str] | None = None,
) -> ChatSummary:
    chat, member = view.chat, view.member
    peer = None
    if view.peer is not None:
        if online_ids is None:
            online = default_chat_hub().is_online(view.peer.user_id)
        else:
            online = view.peer.user_id in online_ids
        peer = _participant(view.peer, online=online)
    return ChatSummary(
        id=chat.id,
        type=chat.type,
        title=chat.title,
        avatar_url=chat.avatar_url,
        peer=peer,
        last_message_at=chat.last_message_at,
        last_message_preview=chat.last_message_preview,
        unread=view.unread,
        pinned=member.pinned,
        muted=member.muted,
        state=member.state,
    )


def _directory_settings(view: DirectoryView) -> DirectorySettings:
    return DirectorySettings(
        discoverable=view.discoverable,
        who_can_dm=view.who_can_dm,  # type: ignore[arg-type]
        who_can_friend=view.who_can_friend,  # type: ignore[arg-type]
    )


def _friend_summary(user, *, online: bool = False) -> FriendSummary:
    return FriendSummary(
        id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        online=online,
    )


def _user_profile(view: ProfileView, *, online: bool = False) -> UserProfile:
    return UserProfile(
        id=view.user.user_id,
        username=view.user.username,
        display_name=view.user.display_name,
        online=online,
        relation=view.relation,
        request_id=view.request_id,
    )


def _friend_request_detail(req, *, peer) -> FriendRequestDetail:
    return FriendRequestDetail(
        id=req.id,
        from_user_id=req.from_user_id,
        to_user_id=req.to_user_id,
        message=req.message,
        status=req.status,
        created_at=req.created_at,
        peer=_friend_summary(peer) if peer is not None else None,
    )


# --- People search (任意搜人) ---


@router.get("/users/search", response_model=UserSearchResponse)
async def search_users(
    user: AuthUser,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    svc: MessagingService = Depends(get_messaging_service),
):
    """Exact-match people-search for starting a chat (任意搜人 + 可见性护栏).

    Returns at most ``limit`` discoverable users; self, blocked pairs, and users
    who opted out of discovery are filtered out by the service.
    """
    users = await svc.search_users(requester_id=user.user_id, query=q, limit=limit)
    data = [_search_result(u) for u in users]
    return UserSearchResponse(data=data, total=len(data))


# --- Chats ---


@router.get("/chats", response_model=ChatListResponse)
async def list_chats(
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """This user's chat list (recent first), with unread counts and dm peers."""
    views = await svc.list_chats(user_id=user.user_id)
    online_ids = default_chat_hub().online_user_ids()
    data = [_chat_summary(v, online_ids=online_ids) for v in views]
    return ChatListResponse(data=data, total=len(data))


@router.post("/chats/dm", response_model=ChatSummary, status_code=201)
async def start_dm(
    body: StartDmRequest,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Open (or reuse) a 1:1 chat with another user (by their user id).

    422 self-dm; 404 unknown/disabled peer; 403 when blocked or the peer only
    accepts friends. Friends open freely; strangers need peer ``who_can_dm=anyone``
    (peer joins as a pending message request).
    """
    view = await svc.start_dm(requester_id=user.user_id, peer_id=body.user_id)
    return _chat_summary(view)


@router.get("/chats/{chat_id}/members", response_model=ChatMembersResponse)
async def list_chat_members(
    chat_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """A chat's members — the group roster (resolves sender names + member panel).

    404 if the requester is not a member (IDOR-safe, no existence leak). Each row
    carries the member's platform-admin and admin-mute flags for the panel.
    """
    members = await svc.list_members(chat_id=chat_id, user_id=user.user_id)
    online_ids = default_chat_hub().online_user_ids()
    data = [
        _participant(
            m.user,
            is_admin=m.is_admin,
            muted_by_admin=m.muted_by_admin,
            online=m.user.user_id in online_ids,
        )
        for m in members
    ]
    return ChatMembersResponse(data=data, total=len(data))


@router.patch("/chats/{chat_id}/membership", response_model=ChatSummary)
async def update_membership(
    chat_id: str,
    body: UpdateMembershipRequest,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Patch this user's per-chat flags (mute / pin). 404 if not a member."""
    view = await svc.set_chat_flags(
        chat_id=chat_id,
        user_id=user.user_id,
        muted=body.muted,
        pinned=body.pinned,
    )
    return _chat_summary(view)


@router.post("/chats/{chat_id}/leave", response_model=StatusResponse)
async def leave_chat(
    chat_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Leave a group chat. 404 if not a member; 422 for a dm or the official
    broadcast chat (can't leave).
    """
    await svc.leave_chat(chat_id=chat_id, user_id=user.user_id)
    return StatusResponse()


# --- Moderation (Stage 3 审核治理: 平台 admin only, gated by AdminUser) ---


@router.delete("/chats/{chat_id}/members/{target_id}", response_model=StatusResponse)
async def kick_member(
    chat_id: str,
    target_id: str,
    admin: AdminUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Remove a member from a group (platform-admin only); posts a system notice.

    403 non-admin (AdminUser gate); 404 unknown chat or non-member target; 422 for
    a dm; 403 when the target is an admin (admins can't be moderated).
    """
    await svc.kick_member(chat_id=chat_id, actor_id=admin.user_id, target_id=target_id)
    return StatusResponse()


@router.post("/chats/{chat_id}/members/{target_id}/mute", response_model=StatusResponse)
async def mute_member(
    chat_id: str,
    target_id: str,
    body: AdminMuteRequest,
    admin: AdminUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Mute / unmute a member (platform-admin only): a muted member can read but
    not send (403 on send). Same gates as kick.
    """
    await svc.set_admin_mute(
        chat_id=chat_id,
        actor_id=admin.user_id,
        target_id=target_id,
        muted=body.muted,
    )
    return StatusResponse()


@router.post("/chats/{chat_id}/announce", response_model=ChatMessageDetail, status_code=201)
async def announce(
    chat_id: str,
    body: AnnounceRequest,
    admin: AdminUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Post an admin announcement as a centered system_card, fanned out to members
    (platform-admin only). 404 unknown chat; 422 for a dm.
    """
    message = await svc.post_announcement(
        chat_id=chat_id, actor_id=admin.user_id, content=body.content
    )
    return ChatMessageDetail.model_validate(message)


@router.get("/chats/{chat_id}/messages", response_model=ChatMessageListResponse)
async def list_chat_messages(
    chat_id: str,
    user: AuthUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    svc: MessagingService = Depends(get_messaging_service),
):
    """A page of a chat's messages (oldest first). 404 if not a member."""
    result = await svc.list_messages(
        chat_id=chat_id, user_id=user.user_id, page=page, page_size=page_size
    )
    return ChatMessageListResponse(
        data=[ChatMessageDetail.model_validate(m) for m in result.messages],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.post("/chats/{chat_id}/messages", response_model=ChatMessageDetail, status_code=201)
async def send_chat_message(
    chat_id: str,
    body: SendChatMessageRequest,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Send a message into a chat the user belongs to.

    Per-user send rate limit first (sheds a flooding account before DB work), then
    the service gates membership (404) and dm blocks (403). Idempotent on
    ``client_msg_id`` — a retry returns the already-stored message.
    """
    await enforce_user_message_rate_limit(user.user_id)
    message = await svc.send_message(
        chat_id=chat_id,
        sender_id=user.user_id,
        content=body.content,
        content_type=body.content_type,
        attachments=[a.model_dump() for a in body.attachments],
        reply_to_message_id=body.reply_to_message_id,
        mentions=[m.model_dump() for m in body.mentions],
        client_msg_id=body.client_msg_id,
    )
    return ChatMessageDetail.model_validate(message)


@router.post(
    "/chats/{chat_id}/messages/{message_id}/recall",
    response_model=ChatMessageDetail,
)
async def recall_chat_message(
    chat_id: str,
    message_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Soft-recall a message (消息IM.md §8 S3).

    Sender within 2 minutes; platform admin may recall any group member message
    (and system_card / official announcements). Body is cleared; row kept.
    Fans ``chat_message_updated`` for in-place client replace (no unread bump).
    404 non-member / missing; 403 outside window or without permission.
    """
    message = await svc.recall_message(
        chat_id=chat_id, message_id=message_id, actor_id=user.user_id
    )
    return ChatMessageDetail.model_validate(message)


@router.patch(
    "/chats/{chat_id}/messages/{message_id}",
    response_model=ChatMessageDetail,
)
async def edit_chat_message(
    chat_id: str,
    message_id: str,
    body: EditChatMessageRequest,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Edit a plain-text message (消息IM.md §8 S4).

    Sender within 15 minutes; recalled / attachments / system_card / official
    refused. Updates ``content`` + ``edited_at``; refreshes list preview when
    this row is still the latest. Fans ``chat_message_updated`` (no unread bump).
    404 non-member / missing; 403 outside window or without permission.
    """
    message = await svc.edit_message(
        chat_id=chat_id,
        message_id=message_id,
        actor_id=user.user_id,
        content=body.content,
    )
    return ChatMessageDetail.model_validate(message)


# --- Attachments (Stage 4 富消息: 图/文件, 复用工作区存储) ---
# Two-step: PUT the raw bytes into the chat's shared workspace, then reference the
# returned path in a send_message attachment. Both are members-only (the service
# gates membership → 404 for non-members), and the chat-scoped backend confines a
# member to this chat's files (no cross-chat IDOR).


@router.put("/chats/{chat_id}/files/{path:path}", response_model=ChatFileUploadResponse)
async def upload_chat_file(
    chat_id: str,
    path: str,
    request: Request,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Upload a chat attachment's bytes (members only) to reference in a send.

    Body is the raw file bytes (no multipart); ``path`` is workspace-relative —
    the client mints a unique ``attachments/...`` path. Bounded by
    ``workspace_upload_max_bytes`` so one request can't exhaust memory; a
    non-member gets 404, an escaping path 422. For an image, a WebP thumbnail is
    generated and its path returned in ``thumb_path``.
    """
    max_bytes = settings.workspace_upload_max_bytes
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")
    data = await request.body()
    if len(data) > max_bytes:
        raise ValidationError(f"文件超出 {max_bytes} 字节的上传上限")
    result = await svc.upload_attachment(
        chat_id=chat_id, user_id=user.user_id, path=path, data=data
    )
    return ChatFileUploadResponse(
        path=path, size_bytes=result.size_bytes, thumb_path=result.thumb_path
    )


@router.get("/chats/{chat_id}/files/{path:path}")
async def download_chat_file(
    chat_id: str,
    path: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Download a chat attachment's bytes (members only; non-member 404).

    Served ``inline`` with the filename so an image opens directly; the client
    fetches it as a blob for rendering and for saving files, so it does not rely
    on the disposition. 404 for a missing path; 422 for an illegal one.
    """
    data = await svc.download_attachment(chat_id=chat_id, user_id=user.user_id, path=path)
    filename = path.rsplit("/", 1)[-1] or "download"
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    # Must use RFC 5987 — bare filename= with CJK latin-1-crashes Starlette ASGI
    # encode (IM 中文图名 → 500 → 客户端 ImageOff). Same helper as workspace downloads.
    return Response(
        content=data,
        media_type=media_type,
        headers=download_headers(filename, disposition="inline"),
    )


@router.post("/chats/{chat_id}/read", response_model=StatusResponse)
async def mark_chat_read(
    chat_id: str,
    body: MarkReadRequest,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Advance this user's read cursor (drives unread counts). 404 if not a member."""
    await svc.mark_read(
        chat_id=chat_id,
        user_id=user.user_id,
        last_read_message_id=body.last_read_message_id,
    )
    return StatusResponse()


# --- Directory settings (discoverability + who-can-DM / who-can-friend) ---


@router.get("/directory", response_model=DirectorySettings)
async def get_directory_settings(
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """This user's discoverability + who-can-DM / who-can-friend (defaults when unset)."""
    view = await svc.get_directory_settings(user_id=user.user_id)
    return _directory_settings(view)


@router.patch("/directory", response_model=DirectorySettings)
async def update_directory_settings(
    body: UpdateDirectorySettingsRequest,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Patch privacy settings; an omitted/null field is left unchanged."""
    view = await svc.update_directory_settings(
        user_id=user.user_id,
        discoverable=body.discoverable,
        who_can_dm=body.who_can_dm,
        who_can_friend=body.who_can_friend,
    )
    return _directory_settings(view)


# --- Friends (消息IM.md §九) ---


@router.get("/users/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(
    user_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """资料卡: display + online + relation; non-visible targets → 404."""
    view = await svc.get_profile(viewer_id=user.user_id, target_id=user_id)
    online = default_chat_hub().is_online(view.user.user_id)
    return _user_profile(view, online=online)


@router.get("/friends", response_model=FriendListResponse)
async def list_friends(
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """通讯录 — accepted friends."""
    friends = await svc.list_friends(user_id=user.user_id)
    online_ids = default_chat_hub().online_user_ids()
    data = [_friend_summary(u, online=u.user_id in online_ids) for u in friends]
    return FriendListResponse(data=data, total=len(data))


@router.get("/friends/requests", response_model=FriendRequestListResponse)
async def list_friend_requests(
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Friend-request inbox: pending incoming + outgoing."""
    box = await svc.list_friend_requests(user_id=user.user_id)
    incoming: list[FriendRequestDetail] = []
    for req in box.incoming:
        peer_view = await svc.get_profile(
            viewer_id=user.user_id, target_id=req.from_user_id
        )
        incoming.append(_friend_request_detail(req, peer=peer_view.user))
    outgoing: list[FriendRequestDetail] = []
    for req in box.outgoing:
        peer_view = await svc.get_profile(
            viewer_id=user.user_id, target_id=req.to_user_id
        )
        outgoing.append(_friend_request_detail(req, peer=peer_view.user))
    return FriendRequestListResponse(incoming=incoming, outgoing=outgoing)


@router.post("/friends/requests", response_model=FriendRequestDetail, status_code=201)
async def create_friend_request(
    body: CreateFriendRequestBody,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Send a friend request (rate-limited like message send)."""
    await enforce_user_message_rate_limit(f"friend:{user.user_id}")
    req = await svc.send_friend_request(
        from_user_id=user.user_id,
        to_user_id=body.user_id,
        message=body.message,
    )
    peer_view = await svc.get_profile(viewer_id=user.user_id, target_id=req.to_user_id)
    return _friend_request_detail(req, peer=peer_view.user)


@router.post("/friends/requests/{request_id}/accept", response_model=FriendRequestDetail)
async def accept_friend_request(
    request_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    req = await svc.accept_friend_request(user_id=user.user_id, request_id=request_id)
    peer_view = await svc.get_profile(
        viewer_id=user.user_id, target_id=req.from_user_id
    )
    return _friend_request_detail(req, peer=peer_view.user)


@router.post("/friends/requests/{request_id}/reject", response_model=FriendRequestDetail)
async def reject_friend_request(
    request_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    req = await svc.reject_friend_request(user_id=user.user_id, request_id=request_id)
    peer_view = await svc.get_profile(
        viewer_id=user.user_id, target_id=req.from_user_id
    )
    return _friend_request_detail(req, peer=peer_view.user)


@router.delete("/friends/requests/{request_id}", response_model=StatusResponse)
async def cancel_friend_request(
    request_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    await svc.cancel_friend_request(user_id=user.user_id, request_id=request_id)
    return StatusResponse()


@router.delete("/friends/{friend_id}", response_model=StatusResponse)
async def remove_friend(
    friend_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    await svc.remove_friend(user_id=user.user_id, friend_id=friend_id)
    return StatusResponse()


# --- Blocking (任意搜人 护栏) ---


@router.get("/blocks", response_model=BlockListResponse)
async def list_blocks(
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """The users this user has blocked."""
    users = await svc.list_blocked(user_id=user.user_id)
    data = [_blocked_user(u) for u in users]
    return BlockListResponse(data=data, total=len(data))


@router.post("/blocks", response_model=StatusResponse)
async def block_user(
    body: BlockUserRequest,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Block a user (symmetric: severs DMs and hides each from the other's search).

    Also drops friendship and cancels pending friend requests (§九).
    422 self-block; 404 unknown target.
    """
    await svc.block_user(user_id=user.user_id, target_id=body.user_id)
    return StatusResponse()


@router.delete("/blocks/{target_id}", response_model=StatusResponse)
async def unblock_user(
    target_id: str,
    user: AuthUser,
    svc: MessagingService = Depends(get_messaging_service),
):
    """Remove a user from the block list (idempotent)."""
    await svc.unblock_user(user_id=user.user_id, target_id=target_id)
    return StatusResponse()
