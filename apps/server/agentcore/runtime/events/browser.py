"""L3 团队浏览器 M1 直播事件工厂（内置浏览器与Agent浏览器提案.md · D13–D14）.

These build the two EPHEMERAL events that ride the per-conversation live SSE bypass
(``GET …/browser/live``): base64 jpeg frames and coarse channel status. They NEVER touch
the turn journal — the live hub emits them onto standalone per-viewer ``EventSink``s.
"""

from __future__ import annotations

from agentcore.runtime.events.types import BrowserLiveState, EventType, SSEEvent


def browser_live_frame(*, frame_b64: str, width: int, height: int) -> SSEEvent:
    """One live screencast frame (base64 jpeg + device dimensions). EPHEMERAL / no seq."""
    return SSEEvent(
        type=EventType.BROWSER_LIVE_FRAME,
        payload={"frame_b64": frame_b64, "width": width, "height": height},
    )


def browser_live_status(state: BrowserLiveState) -> SSEEvent:
    """Coarse live-channel status (started / no_session / session_closed). EPHEMERAL."""
    return SSEEvent(type=EventType.BROWSER_LIVE_STATUS, payload={"state": state})
