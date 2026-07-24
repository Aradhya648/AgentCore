"""L3 团队浏览器 M2 用户接管端点（内置浏览器与Agent浏览器提案.md · D16/D17）.

Owner-only, like every conversation route. Three endpoints (contract pinned, co-owned with
the desktop takeover block):

- ``POST …/browser/takeover`` {action: start|end} — start requires no running turn (D16) +
  a live session; the resulting state (incl. the distinguishable precondition reason) rides
  the response. End is idempotent.
- ``POST …/browser/input`` {events:[…]} — a batch of frame-pixel-space events, valid ONLY
  while takeover is active (else 409). Injection runs through the driver's CDP Input domain;
  it refreshes the session's idle timer and persists NO frames / key / text content (D17).
- ``GET …/browser/takeovers`` — the conversation's audit episodes (timeline card).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_db
from agentcore.api.schemas import (
    BrowserInputRequest,
    BrowserInputResponse,
    BrowserTakeoverActionRequest,
    BrowserTakeoverListResponse,
    BrowserTakeoverRecord,
    BrowserTakeoverState,
)
from agentcore.config import settings
from agentcore.core.errors import ConflictError, ValidationError
from agentcore.core.logging import get_logger
from agentcore.db.repositories import BrowserTakeoverRepository, ConversationRepository
from agentcore.runtime.browser import (
    default_browser_session_registry,
    default_browser_takeover_service,
)
from agentcore.tools.sandbox.browser.protocol import (
    BrowserCommand,
    BrowserDriverCrashedError,
)

from ._helpers import _require_owned_conversation

logger = get_logger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/{conversation_id}/browser/takeover", response_model=BrowserTakeoverState)
async def set_browser_takeover(
    conversation_id: str,
    body: BrowserTakeoverActionRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> BrowserTakeoverState:
    """Start or end user takeover of the conversation's team browser (owner-only)."""
    await _require_owned_conversation(
        conversation_id, user.user_id, ConversationRepository(session)
    )
    service = default_browser_takeover_service()
    if body.action == "start":
        result = await service.start(conversation_id, user.user_id)
    else:
        result = await service.end(conversation_id)
    return BrowserTakeoverState(
        active=result.active,
        reason=result.reason,
        record_id=result.record_id,
        started_at=result.started_at,
    )


@router.post("/{conversation_id}/browser/input", response_model=BrowserInputResponse)
async def submit_browser_input(
    conversation_id: str,
    body: BrowserInputRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> BrowserInputResponse:
    """Inject a batch of takeover input events (owner-only; 409 unless takeover active)."""
    await _require_owned_conversation(
        conversation_id, user.user_id, ConversationRepository(session)
    )
    service = default_browser_takeover_service()
    if not service.is_active(conversation_id):
        raise ConflictError("浏览器未处于用户接管状态，无法注入输入")
    max_events = int(settings.browser_input_max_events)
    if len(body.events) > max_events:
        raise ValidationError(f"单次输入事件过多（上限 {max_events} 条），请分批发送")

    browser = default_browser_session_registry().peek(conversation_id)
    if browser is None:
        # Marked active but the live session vanished under us — end the takeover cleanly
        # (finalizes the record) and tell the client the session is gone.
        await default_browser_session_registry().close(conversation_id)
        raise ConflictError("浏览器会话已失效，接管已结束")

    # Only counts/kinds are observable — event CONTENT (key/text, possibly a password) is
    # never logged (D17).
    events = [ev.model_dump(exclude_none=True) for ev in body.events]
    try:
        result = await browser.send(BrowserCommand(action="input", args={"events": events}))
    except BrowserDriverCrashedError:
        await default_browser_session_registry().close(conversation_id)
        raise ConflictError("浏览器会话已失效，接管已结束") from None
    if not result.ok:
        raise ConflictError("浏览器输入注入失败，请重试或重新开始接管")
    return BrowserInputResponse(injected=int(result.data.get("injected") or 0))


@router.get("/{conversation_id}/browser/takeovers", response_model=BrowserTakeoverListResponse)
async def list_browser_takeovers(
    conversation_id: str,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> BrowserTakeoverListResponse:
    """The conversation's user-takeover audit episodes, newest-first (timeline card)."""
    await _require_owned_conversation(
        conversation_id, user.user_id, ConversationRepository(session)
    )
    rows = await BrowserTakeoverRepository(session).list_for_conversation(conversation_id)
    return BrowserTakeoverListResponse(
        data=[BrowserTakeoverRecord.model_validate(row) for row in rows]
    )
