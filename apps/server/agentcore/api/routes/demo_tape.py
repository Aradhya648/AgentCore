"""Dev-only demo tape catalog + prepare / auto-start launch.

Gated by ``DEMO_TAPE_REPLAY_ENABLED``: when off, every path returns 404 so the
product surface is unchanged.

- **prepare** (primary): create bare cloud conversation + bind tape; user sends
  any message to trigger replay via the existing turn_runner divert.
- **start** (auto-start): same prepare, then kick off ``stream_chat`` with the
  tape's original user prompt as a detached turn — desktop attaches via
  ``GET …/stream``.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_db
from agentcore.api.routes.conversations._helpers import (
    _preflight_owned_chat_turn,
    _preflight_turn_llm,
    emit_preflight_warnings,
    release_request_db_before_sse,
)
from agentcore.api.schemas.demo_tape import (
    DemoTapeCatalogResponse,
    DemoTapeDirectorChapter,
    DemoTapeDirectorChaptersResponse,
    DemoTapeDirectorSeekRequest,
    DemoTapeDirectorSessionsResponse,
    DemoTapeDirectorSpeedRequest,
    DemoTapeDirectorStatus,
    DemoTapePrepareRequest,
    DemoTapePrepareResponse,
    DemoTapeStartRequest,
    DemoTapeStartResponse,
    DemoTapeSummary,
)
from agentcore.conversation.service import stream_chat
from agentcore.core.logging import get_logger
from agentcore.db.repositories import CostEventRepository, MessageRepository
from agentcore.demo_tape import director as director_ctl
from agentcore.demo_tape.catalog import list_tapes
from agentcore.demo_tape.launch import prepare_demo_tape_launch, require_replay_enabled
from agentcore.runtime.events import EventSink
from agentcore.runtime.turn_runs import turn_runs

logger = get_logger(__name__)

router = APIRouter(prefix="/demo-tape", tags=["demo-tape"])


async def _wait_for_user_message(conversation_id: str, *, timeout_s: float = 10.0) -> None:
    from agentcore.db.base import async_session_factory

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        async with async_session_factory() as session:
            msgs, _ = await MessageRepository(session).list_latest(
                conversation_id, limit=1
            )
            if msgs:
                return
        await asyncio.sleep(0.05)
    logger.warning(
        "demo_tape.launch_user_message_timeout",
        conversation_id=conversation_id,
        timeout_s=timeout_s,
    )


async def _wait_for_paused_or_settled(
    conversation_id: str,
    task: asyncio.Task[object],
    *,
    timeout_s: float = 120.0,
) -> None:
    """Block until the tape hits its first durable pause (or the turn ends).

    One-click start returns before the desktop navigates + ``loadRecovery``. If we
    return at user-message time only, a fast tape can pause *after* that recovery
    read — the UI then hydrates the passive「等待开工确认」marker with no
    ResumePrompt, and never grows a collaboration graph. Waiting here makes
    recovery authoritative on first open.
    """
    from agentcore.runtime.suspension_persistence import list_paused_turns

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if task.done():
            return
        frames = await list_paused_turns(conversation_id)
        if frames:
            return
        await asyncio.sleep(0.05)
    logger.warning(
        "demo_tape.launch_pause_timeout",
        conversation_id=conversation_id,
        timeout_s=timeout_s,
    )


@router.get("", response_model=DemoTapeCatalogResponse)
async def get_demo_tape_catalog(_user: AuthUser) -> DemoTapeCatalogResponse:
    """List available tapes when replay is enabled; 404 when the switch is off."""
    require_replay_enabled()
    tapes = [
        DemoTapeSummary(
            id=t.id,
            title=t.title,
            user_prompt=t.user_prompt,
            duration_ms=t.duration_ms,
            event_count=t.event_count,
            turn_count=t.turn_count,
        )
        for t in list_tapes()
    ]
    return DemoTapeCatalogResponse(enabled=True, tapes=tapes)


@router.post("/prepare", response_model=DemoTapePrepareResponse)
async def prepare_demo_tape(
    body: DemoTapePrepareRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> DemoTapePrepareResponse:
    """Create cloud session + bind tape; do **not** start a turn.

    The client navigates into the empty conversation; the next user message
    triggers tape replay (turn_runner divert). ``user_prompt`` is the tape's
    suggested opening line for the operator to type or paste.
    """
    prepared = await prepare_demo_tape_launch(
        tape_id=body.tape_id,
        user=user,
        session=session,
        speed=body.speed,
        max_gap_ms=body.max_gap_ms,
    )
    logger.info(
        "demo_tape.prepare_ready",
        conversation_id=prepared.conversation_id,
        tape_id=prepared.tape.id,
    )
    return DemoTapePrepareResponse(
        conversation_id=prepared.conversation_id,
        tape_id=prepared.tape.id,
        title=prepared.title,
        user_prompt=prepared.user_prompt,
        speed=prepared.speed,
        max_gap_ms=prepared.max_gap_ms,
    )


@router.post("/start", response_model=DemoTapeStartResponse)
async def start_demo_tape(
    body: DemoTapeStartRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
    x_client_platform: Annotated[str | None, Header(alias="X-Client-Platform")] = None,
) -> DemoTapeStartResponse:
    """Create cloud session, bind tape, start replay turn (attach via GET …/stream)."""
    prepared = await prepare_demo_tape_launch(
        tape_id=body.tape_id,
        user=user,
        session=session,
        speed=body.speed,
        max_gap_ms=body.max_gap_ms,
    )

    preflight = await _preflight_turn_llm(
        session=session,
        user=user,
        cost_repo=CostEventRepository(session),
        needs_tools=True,
    )
    await release_request_db_before_sse(session)

    sink = EventSink()
    emit_preflight_warnings(sink, preflight)
    task = asyncio.create_task(
        stream_chat(
            conversation_id=prepared.conversation_id,
            user_message=prepared.user_prompt,
            user_id=user.user_id,
            sink=sink,
            attachments=[],
            llm_credentials=preflight.credentials,
            llm_supports_tools=preflight.supports_tools,
            x_client_platform=x_client_platform,
        )
    )
    turn_runs.register(
        conversation_id=prepared.conversation_id,
        task=task,
        sink=sink,
    )
    await _wait_for_user_message(prepared.conversation_id)
    await _wait_for_paused_or_settled(prepared.conversation_id, task)

    logger.info(
        "demo_tape.started",
        conversation_id=prepared.conversation_id,
        tape_id=prepared.tape.id,
    )
    return DemoTapeStartResponse(
        conversation_id=prepared.conversation_id,
        tape_id=prepared.tape.id,
        title=prepared.title,
        user_prompt=prepared.user_prompt,
        speed=prepared.speed,
        max_gap_ms=prepared.max_gap_ms,
    )


# ── Director console (metronome control; same DEMO_TAPE_REPLAY_ENABLED gate) ─

# Replay mode disables uvicorn WatchFiles; reload director_page from disk by mtime
# so the second-screen tab can live-reload without a backend restart.
_director_mtime_ns: int | None = None


def _director_source_path() -> Path:
    import agentcore.demo_tape.director_page as page

    return Path(page.__file__).resolve()


def _director_rev() -> str:
    return str(_director_source_path().stat().st_mtime_ns)


def _fresh_director_html() -> str:
    """Serve latest DIRECTOR_HTML, reloading the module when the file mtime changes."""
    global _director_mtime_ns
    import agentcore.demo_tape.director_page as page

    mtime_ns = _director_source_path().stat().st_mtime_ns
    if _director_mtime_ns != mtime_ns:
        page = importlib.reload(page)
        _director_mtime_ns = mtime_ns
    rev = str(mtime_ns)
    html = page.DIRECTOR_HTML
    needle = '<meta name="director-rev"'
    if needle in html:
        start = html.index(needle)
        end = html.index(">", start) + 1
        html = html[:start] + f'<meta name="director-rev" content="{rev}" />' + html[end:]
    else:
        html = html.replace("</head>", f'<meta name="director-rev" content="{rev}" />\n</head>', 1)
    return html


def _status_model(raw: dict) -> DemoTapeDirectorStatus:
    return DemoTapeDirectorStatus(**raw)


@router.get("/director", response_class=HTMLResponse, include_in_schema=False)
async def director_console_page() -> HTMLResponse:
    """Bare local control page for OBS second-screen directing (dev-only)."""
    require_replay_enabled()
    return HTMLResponse(_fresh_director_html())


@router.get("/director/rev", include_in_schema=False)
async def director_console_rev() -> dict[str, str]:
    """File mtime stamp for the director HTML live-reload poller."""
    require_replay_enabled()
    return {"rev": _director_rev()}


@router.get("/director/sessions", response_model=DemoTapeDirectorSessionsResponse)
async def director_list_sessions(_user: AuthUser) -> DemoTapeDirectorSessionsResponse:
    require_replay_enabled()
    sessions = [_status_model(s) for s in director_ctl.list_sessions()]
    return DemoTapeDirectorSessionsResponse(sessions=sessions)


@router.get(
    "/director/{conversation_id}/status",
    response_model=DemoTapeDirectorStatus,
)
async def director_status(
    conversation_id: str, _user: AuthUser
) -> DemoTapeDirectorStatus:
    return _status_model(director_ctl.status_for_conversation(conversation_id))


@router.get(
    "/director/{conversation_id}/chapters",
    response_model=DemoTapeDirectorChaptersResponse,
)
async def director_chapters(
    conversation_id: str, _user: AuthUser
) -> DemoTapeDirectorChaptersResponse:
    chapters = [
        DemoTapeDirectorChapter(
            id=c.id, label=c.label, t_ms=c.t_ms, event_index=c.event_index
        )
        for c in director_ctl.chapters_for_conversation(conversation_id)
    ]
    return DemoTapeDirectorChaptersResponse(
        conversation_id=conversation_id, chapters=chapters
    )


@router.post(
    "/director/{conversation_id}/pause",
    response_model=DemoTapeDirectorStatus,
)
async def director_pause(
    conversation_id: str, _user: AuthUser
) -> DemoTapeDirectorStatus:
    return _status_model(director_ctl.pause(conversation_id))


@router.post(
    "/director/{conversation_id}/resume",
    response_model=DemoTapeDirectorStatus,
)
async def director_resume(
    conversation_id: str, _user: AuthUser
) -> DemoTapeDirectorStatus:
    return _status_model(director_ctl.resume_soft(conversation_id))


@router.post(
    "/director/{conversation_id}/speed",
    response_model=DemoTapeDirectorStatus,
)
async def director_speed(
    conversation_id: str,
    body: DemoTapeDirectorSpeedRequest,
    _user: AuthUser,
) -> DemoTapeDirectorStatus:
    return _status_model(director_ctl.set_speed(conversation_id, body.speed))


@router.post(
    "/director/{conversation_id}/seek",
    response_model=DemoTapeDirectorStatus,
)
async def director_seek(
    conversation_id: str,
    body: DemoTapeDirectorSeekRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> DemoTapeDirectorStatus:
    # Seek may restart a turn or auto-resume team_preview — same LLM gate as send.
    preflight = await _preflight_owned_chat_turn(conversation_id, user, session)
    await release_request_db_before_sse(session)

    def _setup(sink: EventSink) -> None:
        emit_preflight_warnings(sink, preflight)

    raw = await director_ctl.seek(
        conversation_id=conversation_id,
        user_id=user.user_id,
        llm_credentials=preflight.credentials,
        llm_supports_tools=preflight.supports_tools,
        setup_sink=_setup,
        t_ms=body.t_ms,
        event_index=body.event_index,
        chapter_id=body.chapter_id,
    )
    return _status_model(raw)
