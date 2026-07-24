"""L3 团队浏览器 M2 接管 API schemas（内置浏览器与Agent浏览器提案.md · D16/D17）.

Co-owned (pinned) with the desktop takeover block: the takeover state is carried by the
POST response (``BrowserTakeoverState``), input is a batch of frame-pixel-space events, and
the timeline card reads the audit episodes. NO frame/key/text content is ever persisted or
echoed back (D17) — responses carry only counts + who/when/why.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class BrowserTakeoverActionRequest(BaseModel):
    """Start or end user takeover of the conversation's team browser (owner-only)."""

    action: Literal["start", "end"]


class BrowserTakeoverState(BaseModel):
    """The takeover state a POST …/browser/takeover returns (D16: state on the response).

    ``reason`` distinguishes every outcome without an HTTP error: ``started`` / ``ended`` on
    success; ``already_active`` (start when one is running — still active); ``turn_running``
    / ``no_session`` (start preconditions unmet); ``not_active`` (end when none is running).
    ``active`` reflects the resulting state; ``started_at`` is set while active.
    """

    active: bool
    reason: Literal[
        "started", "ended", "already_active", "turn_running", "no_session", "not_active"
    ]
    record_id: str | None = None
    started_at: datetime | None = None


class MouseInputEvent(BaseModel):
    """A pointer event in frame-pixel space (the driver rescales to the viewport)."""

    kind: Literal["mouse"]
    type: Literal["down", "up", "move", "wheel"]
    x: float
    y: float
    button: Literal["left", "right", "middle"] | None = None
    delta_x: float | None = None
    delta_y: float | None = None
    click_count: int | None = None


class KeyInputEvent(BaseModel):
    """A key event. ``modifiers`` is a CDP bitmask or a list of names (alt/ctrl/meta/shift).

    Use this for non-text keys (Enter / Backspace / arrows / shortcuts); actual typed text
    should ride a ``text`` event so it inserts verbatim (and never lands in any log — D17).
    """

    kind: Literal["key"]
    type: Literal["down", "up"]
    key: str
    code: str | None = None
    modifiers: int | list[str] | None = None


class TextInputEvent(BaseModel):
    """Verbatim text insertion (IME-style). Content is never logged/persisted (D17)."""

    kind: Literal["text"]
    text: str


BrowserInputEvent = Annotated[
    MouseInputEvent | KeyInputEvent | TextInputEvent, Field(discriminator="kind")
]


class BrowserInputRequest(BaseModel):
    """A batch of takeover input events (only valid while takeover is active; else 409)."""

    events: list[BrowserInputEvent]


class BrowserInputResponse(BaseModel):
    """Result of an input batch: how many events were dispatched (no content echoed)."""

    injected: int


class BrowserTakeoverRecord(BaseModel):
    """One audit episode for the timeline card (who/when/why — never content, D17)."""

    id: str
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None

    model_config = {"from_attributes": True}


class BrowserTakeoverListResponse(BaseModel):
    data: list[BrowserTakeoverRecord]
