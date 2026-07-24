"""L3 团队浏览器 M1 直播 SSE 旁路端点（内置浏览器与Agent浏览器提案.md · D13）.

``GET /v1/conversations/{conversation_id}/browser/live`` — owner-only, like every other
conversation endpoint. Attaches the caller as a live viewer of that conversation's browser
screencast and streams ``browser_live_frame`` / ``browser_live_status`` events (EPHEMERAL —
never journaled). Screencast starts on the first viewer and stops on the last (D13); a viewer
with no live session gets ``no_session`` and stays attached until one appears.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from agentcore.api.dependencies import AuthUser, get_db
from agentcore.api.sse import _HEARTBEAT_INTERVAL_S, _format_sse
from agentcore.db.repositories import ConversationRepository
from agentcore.runtime.browser.live import (
    BrowserLiveHub,
    BrowserLiveViewer,
    default_browser_live_hub,
)

from ._helpers import _require_owned_conversation, release_request_db_before_sse

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _live_generator(
    hub: BrowserLiveHub, conversation_id: str, viewer: BrowserLiveViewer
) -> AsyncIterator[str]:
    """Drain the viewer's queue as SSE, heartbeat while idle, detach on disconnect.

    A detach on disconnect is scheduled (not awaited) so it always completes even as the
    request is being cancelled — otherwise a dropped connection could leak a viewer and keep
    the screencast running with nobody watching.
    """
    try:
        while True:
            try:
                event = await asyncio.wait_for(viewer.get(), _HEARTBEAT_INTERVAL_S)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event is None:
                break
            yield _format_sse(event)
    finally:
        hub.detach_soon(conversation_id, viewer)


@router.get("/{conversation_id}/browser/live")
async def stream_browser_live(
    conversation_id: str,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Attach as a live viewer of the conversation's browser screencast (owner-only)."""
    conv_repo = ConversationRepository(session)
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    # Release the request-scoped DB connection before the long-lived stream (mirrors chat SSE).
    await release_request_db_before_sse(session)

    hub = default_browser_live_hub()
    viewer = await hub.attach(conversation_id)
    return StreamingResponse(
        _live_generator(hub, conversation_id, viewer),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
