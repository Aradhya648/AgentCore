"""L3 团队浏览器 M1 直播 SSE payload wire models（内置浏览器与Agent浏览器提案.md · D13–D14）.

The live-frame bypass (D13) rides a per-conversation SSE side-channel — NOT the turn
journal. Both events are EPHEMERAL (see ``events/disposition.py``): base64 jpeg frames and
coarse status never persist. Contract is co-owned with the desktop 直播 tab block and is
pinned: envelope stays the standard ``{type, payload}``.
"""

from __future__ import annotations

from agentcore.runtime.events.payloads._base import WirePayload

# The live channel's coarse state (co-pinned with desktop) — single source in the
# dependency-light types module, re-exported here for the wire-model + TS registry.
from agentcore.runtime.events.types import BrowserLiveState  # noqa: F401 (re-exported for TS)


class BrowserLiveFramePayload(WirePayload):
    """One live screencast frame on ``browser_live_frame`` (D14).

    ``frame_b64`` is a base64-encoded jpeg exactly as CDP ``Page.screencastFrame`` delivers
    it (no host decode/re-encode on the hot path). ``width``/``height`` are the frame's
    device pixel dimensions so the client can size the canvas without decoding first.
    """

    frame_b64: str
    width: int
    height: int


class BrowserLiveStatusPayload(WirePayload):
    """Live channel status on ``browser_live_status`` (D14).

    ``started`` — a live browser session exists and screencast is now flowing to viewers;
    ``no_session`` — the viewer attached but the conversation has no live browser session;
    ``session_closed`` — the watched session was recycled / closed (idle only when unwatched,
    or max-lifetime).
    """

    state: BrowserLiveState
