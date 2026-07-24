"""Messaging (消息页 = 找人 IM; 消息IM.md) schemas.

A separate surface from the AI 对话 page: human↔human chat + an official account.
Shares the frontend chat core, not the AI conversation/messages schemas.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .messages import StoredAttachment


class UserSearchResult(BaseModel):
    """A discoverable user surfaced by people-search (任意搜人, exact match)."""

    id: str
    username: str
    display_name: str

    model_config = {"from_attributes": True}


class UserSearchResponse(BaseModel):
    data: list[UserSearchResult]
    total: int


class ChatParticipant(BaseModel):
    """A human shown on a chat (the peer of a dm; members of a group)."""

    id: str
    username: str
    display_name: str
    # Platform admin (创始团队 = the 内测群's moderators); lets the roster badge
    # official accounts and hide kick/mute on them. False for the dm peer.
    is_admin: bool = False
    # Admin-imposed 禁言 (Stage 3): this group member can read but not send.
    muted_by_admin: bool = False

    model_config = {"from_attributes": True}


class ChatSummary(BaseModel):
    """One row in the IM chat list (消息页左栏), plus this user's per-chat state."""

    id: str
    type: Literal["dm", "group", "official"]
    title: str | None = None
    avatar_url: str | None = None
    # The other human in a dm (None for group/official); drives the list-row name.
    peer: ChatParticipant | None = None
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    unread: int = 0
    pinned: bool = False
    muted: bool = False
    # 'pending' = a stranger message request awaiting this user's accept (消息请求).
    state: Literal["accepted", "pending"] = "accepted"


class ChatListResponse(BaseModel):
    data: list[ChatSummary]
    total: int


class ChatMembersResponse(BaseModel):
    """A chat's members (group roster: resolves sender names + the member panel)."""

    data: list[ChatParticipant]
    total: int


class StartDmRequest(BaseModel):
    """Open (or reuse) a 1:1 chat with another user (by their user id)."""

    user_id: str = Field(..., min_length=1, max_length=64)


class UpdateMembershipRequest(BaseModel):
    """Patch this user's per-chat flags (mute / pin); omitted fields unchanged."""

    muted: bool | None = None
    pinned: bool | None = None


class AdminMuteRequest(BaseModel):
    """Admin 禁言 toggle for a group member (muted = can read, can't send)."""

    muted: bool


class AnnounceRequest(BaseModel):
    """Post an admin announcement into a chat as a centered system_card (官方公告)."""

    content: str = Field(..., min_length=1, max_length=2000)


class ChatMessageDetail(BaseModel):
    id: str
    chat_id: str
    # NULL sender = the official/system account.
    sender_user_id: str | None
    sender_type: Literal["user", "official", "agent"]
    content: str | None
    content_type: Literal["text", "image", "file", "system_card"]
    attachments: list[StoredAttachment] = Field(default_factory=list)
    # system_card deep-link payload (e.g. {kind, conversation_id}); None otherwise.
    payload: dict[str, Any] | None = None
    reply_to_message_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageListResponse(BaseModel):
    data: list[ChatMessageDetail]
    total: int
    page: int
    page_size: int


class SendChatMessageRequest(BaseModel):
    """Send a message into a chat: plain text, or a 富消息 carrying attachments.

    ``content`` is optional when ``attachments`` is non-empty (an image/file-only
    message has no caption); otherwise it is required. ``content_type`` tells the
    client how to render it — ``image`` for an inline gallery, ``file`` for
    download chips — and is derived by the sender from what it uploaded.
    """

    content: str | None = Field(None, max_length=32000)
    content_type: Literal["text", "image", "file"] = "text"
    # Pre-uploaded via PUT /messages/chats/{id}/files/{path}; referenced here by
    # their returned workspace paths. Capped low (a single message, not a folder).
    attachments: list[StoredAttachment] = Field(default_factory=list, max_length=9)
    # Client-minted id for retry-safe idempotent send (dedup at the unique index).
    client_msg_id: str | None = Field(None, max_length=100)
    reply_to_message_id: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def _require_content_or_attachments(self) -> "SendChatMessageRequest":
        if not (self.content and self.content.strip()) and not self.attachments:
            raise ValueError("消息内容与附件不能同时为空")
        return self


class ChatFileUploadResponse(BaseModel):
    """Result of a chat attachment upload (Stage 4 富消息).

    Mirrors ``UploadFileResponse`` but adds ``thumb_path``: a generated WebP
    thumbnail's workspace path for images (None otherwise), which the sender
    copies onto the message's ``StoredAttachment`` for cheap inline previews.
    """

    path: str
    size_bytes: int
    thumb_path: str | None = None


class MarkReadRequest(BaseModel):
    """Advance this user's read cursor (drives unread counts + read receipts)."""

    last_read_message_id: str = Field(..., min_length=1, max_length=64)


class DirectorySettings(BaseModel):
    """A user's discoverability + who-can-DM privacy (任意搜人 护栏)."""

    discoverable: bool = True
    who_can_dm: Literal["anyone", "contacts"] = "anyone"

    model_config = {"from_attributes": True}


class UpdateDirectorySettingsRequest(BaseModel):
    discoverable: bool | None = None
    who_can_dm: Literal["anyone", "contacts"] | None = None


class BlockUserRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)


class BlockedUser(BaseModel):
    id: str
    username: str
    display_name: str

    model_config = {"from_attributes": True}


class BlockListResponse(BaseModel):
    data: list[BlockedUser]
    total: int
