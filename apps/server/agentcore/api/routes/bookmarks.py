"""消息收藏 (bookmarks) routes: 跨设备保存对话内关键消息 → 侧栏「已收藏」.

Every route is owner-scoped. Creating a bookmark verifies the user owns the
message's conversation (IDOR-safe — a guessed message id from another account
404s); listing / removing / the per-conversation star-state read are all filtered
by the caller's ``user_id``, so a user only ever sees or mutates their own
bookmarks. Server storage is what makes a bookmark 跨设备: any signed-in device
fetches the same set.
"""

from fastapi import APIRouter, Depends, Query

from agentcore.api.dependencies import (
    AuthUser,
    get_bookmark_repo,
    get_conversation_repo,
    get_message_repo,
)
from agentcore.api.schemas import (
    BookmarkIdsResponse,
    BookmarkItem,
    BookmarkListResponse,
    CreateBookmarkRequest,
    StatusResponse,
)
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import (
    BookmarkRepository,
    ConversationRepository,
    MessageRepository,
)

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])

# The「已收藏」list is a personal, curated set — cap generously but bounded.
_LIST_LIMIT = 200
# A saved-message preview: enough to recognise the reply, whitespace-collapsed.
_SNIPPET_CHARS = 140


def _snippet(content: str | None) -> str | None:
    """A one-line preview of a saved message (None for an empty/whitespace body)."""
    if not content:
        return None
    flat = " ".join(content.split())
    if not flat:
        return None
    return f"{flat[:_SNIPPET_CHARS]}…" if len(flat) > _SNIPPET_CHARS else flat


@router.post("", response_model=BookmarkItem, status_code=201)
async def create_bookmark(
    body: CreateBookmarkRequest,
    user: AuthUser,
    bookmark_repo: BookmarkRepository = Depends(get_bookmark_repo),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    msg_repo: MessageRepository = Depends(get_message_repo),
):
    """Bookmark a message (idempotent — re-adding returns the existing row).

    404 when the user doesn't own the conversation or the message isn't in it, so a
    bookmark can never point at another account's content.
    """
    conv = await conv_repo.get_by_id(body.conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    msg = await msg_repo.get_by_id(body.message_id, conversation_id=body.conversation_id)
    if not msg:
        raise NotFoundError("消息不存在")
    bookmark = await bookmark_repo.add(
        user_id=user.user_id,
        conversation_id=body.conversation_id,
        message_id=body.message_id,
    )
    return BookmarkItem(
        id=bookmark.id,
        conversation_id=bookmark.conversation_id,
        message_id=bookmark.message_id,
        conversation_title=conv.title,
        role=msg.role,
        snippet=_snippet(msg.content),
        created_at=bookmark.created_at,
    )


@router.get("", response_model=BookmarkListResponse)
async def list_bookmarks(
    user: AuthUser,
    bookmark_repo: BookmarkRepository = Depends(get_bookmark_repo),
):
    """The user's「已收藏」list, newest-first (跨设备 — server-stored).

    Bookmarks whose message/conversation was removed or whose conversation was
    soft-deleted are filtered out by the repository join, so every item is
    jump-able.
    """
    rows = await bookmark_repo.list_by_user(user.user_id, limit=_LIST_LIMIT)
    return BookmarkListResponse(
        data=[
            BookmarkItem(
                id=bm.id,
                conversation_id=bm.conversation_id,
                message_id=bm.message_id,
                conversation_title=title,
                role=msg.role,
                snippet=_snippet(msg.content),
                created_at=bm.created_at,
            )
            for bm, msg, title in rows
        ]
    )


@router.get("/ids", response_model=BookmarkIdsResponse)
async def list_bookmark_ids(
    user: AuthUser,
    conversation_id: str = Query(..., description="限定某对话，返回其中已收藏的消息 id"),
    bookmark_repo: BookmarkRepository = Depends(get_bookmark_repo),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """The bookmarked message ids within one conversation (client star state).

    Owner-scopes the conversation first (404 for a non-owner) so ids never leak.
    """
    conv = await conv_repo.get_by_id(conversation_id, user_id=user.user_id)
    if not conv:
        raise NotFoundError("对话不存在")
    ids = await bookmark_repo.list_message_ids_for_conversation(
        user.user_id, conversation_id
    )
    return BookmarkIdsResponse(message_ids=ids)


@router.delete("/{message_id}", response_model=StatusResponse)
async def remove_bookmark(
    message_id: str,
    user: AuthUser,
    bookmark_repo: BookmarkRepository = Depends(get_bookmark_repo),
):
    """Un-bookmark a message (idempotent — a no-match is still 200)."""
    await bookmark_repo.remove(user_id=user.user_id, message_id=message_id)
    return StatusResponse()
