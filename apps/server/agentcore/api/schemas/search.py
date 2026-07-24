"""Global search (全局搜索 Tier 1: 跨对话/消息/文件夹关键词检索) schemas.

One keyword query fans out over the user's own conversations (title), messages
(content) and folders (name) — see 前端技术与架构.md §9.8. Backed by ILIKE
(no tsvector — stock PG doesn't segment Chinese); results are owner-scoped.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SearchItem(BaseModel):
    """One hit in a section. Field meaning depends on the section ``type``:

    - conversation: ``id`` = conversation id, ``title`` = its title.
    - message: ``id`` = message id, ``conversation_id`` = where to jump,
      ``title`` = the owning conversation's title (list-row context), ``role`` =
      user/assistant, ``snippet`` = match window with ``match_start``/``match_end``
      offsets into the snippet for client-side highlighting.
    - folder: ``id`` = folder id, ``title`` = its name.
    """

    id: str
    title: str | None = None
    conversation_id: str | None = None
    role: str | None = None
    snippet: str | None = None
    match_start: int | None = None
    match_end: int | None = None
    updated_at: datetime | None = None


class SearchSection(BaseModel):
    """Hits of one entity type, recency-ordered (newest first)."""

    type: Literal["conversation", "message", "folder"]
    items: list[SearchItem]


class SearchResponse(BaseModel):
    query: str
    sections: list[SearchSection]
