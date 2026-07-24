"""L3 团队浏览器 M2 接管留档模型（内置浏览器与Agent浏览器提案.md · D17）.

``BrowserTakeoverRow`` is the durable audit record of one user-takeover episode of a
conversation's team-browser session: who took over, when it started, and when (and why)
it ended. A row is inserted at takeover START (``ended_at`` NULL = in progress) and
completed at END — and END lands on **every** teardown path (explicit end / session
recycled or crashed / process shutdown / conversation delete cascade), so an episode is
never left silently open. **No frame or key/text content is ever stored here** (D17: the
input bytes may be a password) — only the coarse who/when/why.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from agentcore.db.base import Base

from ._helpers import _new_uuid


class BrowserTakeoverRow(Base):
    """One user-takeover episode of a conversation's team browser (D17 留档).

    Lifecycle (no DB FK — app-level, per repo convention): created on takeover start,
    finalized (``ended_at`` + ``end_reason``) on any end path. Rows persist as an audit
    trail (the GET …/browser/takeovers timeline) — they are NOT time-pruned.
    """

    __tablename__ = "browser_takeovers"
    __table_args__ = (
        # The only list query: one conversation's episodes, newest-first (timeline card).
        Index("ix_browser_takeovers_conversation_started", "conversation_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), primary_key=True, default=_new_uuid)
    conversation_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False))
    user_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=False), index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    # NULL while the takeover is in progress; stamped on every end path.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Which end path closed it (user_end / reaped / stale / closed / shutdown / …) — a
    # coarse audit token only, never event content.
    end_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
