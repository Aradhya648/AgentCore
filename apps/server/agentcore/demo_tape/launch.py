"""Demo tape launch helpers: create cloud session + bind tape (dev-only).

``prepare_demo_tape_launch`` only binds — it does **not** start a turn.
The ``/start`` route may kick off a detached turn after prepare returns;
``/prepare`` leaves the session idle for the operator to send a message.
Keeps this package free of ``api.routes`` imports.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.config import settings
from agentcore.conversation.common import default_permission_axes_for_user
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.core.logging import get_logger
from agentcore.db.models import User
from agentcore.db.repositories import ConversationRepository
from agentcore.demo_tape.binding import write_binding
from agentcore.demo_tape.catalog import TapeInfo, resolve_tape
from agentcore.demo_tape.export import load_tape

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreparedLaunch:
    conversation_id: str
    tape: TapeInfo
    user_prompt: str
    title: str
    speed: float
    max_gap_ms: int


def require_replay_enabled() -> None:
    if not settings.demo_tape_replay_enabled:
        raise NotFoundError("演示磁带回放未开启")


def _user_prompt_for(info: TapeInfo) -> str:
    if info.user_prompt:
        return info.user_prompt
    tape_doc = load_tape(info.path)
    meta = tape_doc.get("meta") if isinstance(tape_doc.get("meta"), dict) else {}
    return str(meta.get("user_prompt") or "").strip()


async def prepare_demo_tape_launch(
    *,
    tape_id: str,
    user: User,
    session: AsyncSession,
    speed: float | None = None,
    max_gap_ms: int | None = None,
) -> PreparedLaunch:
    """Create a bare cloud conversation and bind ``tape_id``.

    Does **not** start the turn — the route registers ``stream_chat`` into
    ``turn_runs`` so the client can attach via ``GET …/stream``.
    """
    require_replay_enabled()
    info = resolve_tape(tape_id)
    if info is None:
        raise NotFoundError(f"磁带不存在: {tape_id}")
    user_prompt = _user_prompt_for(info)
    if not user_prompt:
        raise ValidationError("磁带缺少原始用户消息（meta.user_prompt）")

    title = (info.title or info.id)[:500]
    bind_speed = float(speed if speed is not None else settings.demo_tape_speed)
    bind_gap = int(max_gap_ms if max_gap_ms is not None else settings.demo_tape_max_gap_ms)

    axes = await default_permission_axes_for_user(session, user.user_id)
    conv = await ConversationRepository(session).create(
        user_id=user.user_id,
        title=title,
        folder_id=None,
        local_container_root_id=None,
        permission_axes=axes.to_dict(),
    )

    write_binding(
        conv.id,
        tape=info.repo_relative,
        speed=bind_speed,
        max_gap_ms=bind_gap,
    )

    logger.info(
        "demo_tape.prepared",
        conversation_id=conv.id,
        tape_id=info.id,
        speed=bind_speed,
        max_gap_ms=bind_gap,
    )
    return PreparedLaunch(
        conversation_id=conv.id,
        tape=info,
        user_prompt=user_prompt,
        title=title,
        speed=bind_speed,
        max_gap_ms=bind_gap,
    )
