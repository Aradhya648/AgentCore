"""消息收藏 (bookmarks) schemas: 跨设备保存的对话内消息.

A bookmark is a per-user pointer to one message (对话内消息 bookmark → 侧栏
「已收藏」). Server-stored so it is reachable from any device; the list items carry
just enough context (owning conversation title, role, a content snippet) to
recognise a saved message before jumping to it.
"""

from datetime import datetime

from pydantic import BaseModel


class CreateBookmarkRequest(BaseModel):
    conversation_id: str
    message_id: str


class BookmarkItem(BaseModel):
    """One saved message in the「已收藏」view.

    ``id`` = bookmark id; ``created_at`` = when it was bookmarked (the list sort
    key). ``conversation_id`` / ``message_id`` are the jump target;
    ``conversation_title`` + ``role`` + ``snippet`` give recognisable context.
    """

    id: str
    conversation_id: str
    message_id: str
    conversation_title: str | None = None
    role: str | None = None
    snippet: str | None = None
    created_at: datetime


class BookmarkListResponse(BaseModel):
    data: list[BookmarkItem]


class BookmarkIdsResponse(BaseModel):
    """The bookmarked message ids within one conversation (client star state)."""

    message_ids: list[str]
