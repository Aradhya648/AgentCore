"""Browser Session API schemas — multi ``session_id`` + takeover (M0 / M2).

Co-owned with the desktop BrowserPanel: list/create/close sessions; takeover state is
carried by the POST response; input is a batch of frame-pixel-space events. NO frame /
key / text content is ever persisted or echoed back (D17).
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class BrowserSessionView(BaseModel):
    """One live browser session entry (list / create response)."""

    session_id: str
    conversation_id: str
    host_kind: Literal["sandbox", "local"] = "sandbox"
    run_id: str | None = None
    control: Literal["agent", "user"] = "agent"
    created_at: float
    last_used: float
    # L7 最小：最近导航 url/title（可选）。
    url: str | None = None
    title: str | None = None


class BrowserSessionNavPatch(BaseModel):
    """PATCH body for L7 idle / Bridge navigate url·title 回写."""

    url: str | None = None
    title: str | None = None


class BrowserSessionNavigateRequest(BaseModel):
    """POST …/browser/sessions/{id}/navigate — owner address-bar navigate."""

    url: str = Field(..., min_length=1)


class BrowserSessionListResponse(BaseModel):
    data: list[BrowserSessionView]
    active_session_id: str | None = None


class BrowserSessionCreateRequest(BaseModel):
    """Create a new browser session tab for the conversation."""

    host_kind: Literal["sandbox", "local"] = "sandbox"
    activate: bool = True


class BrowserTakeoverActionRequest(BaseModel):
    """Start or end user takeover of a browser session (owner-only).

    ``session_id`` optional — omit to resolve the conversation's unique/active session.
    """

    action: Literal["start", "end"]
    session_id: str | None = None


class BrowserTakeoverState(BaseModel):
    """The takeover state a POST …/browser/takeover returns.

    ``reason`` distinguishes every outcome without an HTTP error: ``started`` / ``ended`` on
    success; ``already_active`` (start when one is running — still active); ``no_session``
    (no live session to take over); ``not_active`` (end when none is running).
    ``turn_running`` is retained for wire compat but is never produced after D8 (anytime
    takeover). ``active`` reflects the resulting state; ``started_at`` is set while active.
    """

    active: bool
    reason: Literal[
        "started", "ended", "already_active", "turn_running", "no_session", "not_active"
    ]
    record_id: str | None = None
    started_at: datetime | None = None
    session_id: str | None = None


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
    session_id: str | None = None


class BrowserInputResponse(BaseModel):
    """Result of an input batch: how many events were dispatched (no content echoed)."""

    injected: int


class BrowserTakeoverRecord(BaseModel):
    """One audit episode for the timeline card (who/when/why — never content, D17)."""

    id: str
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    session_id: str | None = None

    model_config = {"from_attributes": True}


class BrowserTakeoverListResponse(BaseModel):
    data: list[BrowserTakeoverRecord]
