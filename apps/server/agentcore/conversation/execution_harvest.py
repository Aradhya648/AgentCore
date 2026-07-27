"""System-initiated harvest closing turn (异步团队产出投递 · 支柱 C).

When a detached coordination drive finishes, the harvester calls
:func:`run_harvest_closing_turn` to spawn a CEO turn that adopts the live
execution, consumes queued ``ALL_COMPLETED``, and delivers a final assistant
message. Meta stamps ``origin=execution_harvest`` for attribution.

Mirrors :mod:`agentcore.conversation.stage_card_resolve` ``run_and_persist`` usage.
"""

from __future__ import annotations

import contextlib

from agentcore.conversation.common import (
    resolve_conversation_history_access,
    resolve_local_binding,
    resolve_memory_enabled,
    resolve_permission_preset,
    resolve_profile_set,
)
from agentcore.conversation.history import load_chat_context
from agentcore.conversation.turn_backend import build_turn_backend
from agentcore.conversation.turn_runner import run_and_persist
from agentcore.core.logging import get_logger
from agentcore.core.types import preset_to_autonomy
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import BoardRepository, ConversationRepository
from agentcore.push import PushNotification, notify_user
from agentcore.runtime.events import EventSink
from agentcore.runtime.turn_runs import turn_runs
from agentcore.workspace.locate import workspace_storage_key
from agentcore.workspace.locks import workspace_lock

logger = get_logger(__name__)

_HARVEST_USER_TEXT = (
    "【系统收口】后台团队任务已全部完成。请综合队员产出，按终稿纪律交付给老板："
    "交付物在前，过程简述至多一段；勿粘贴协调事件原文。"
)


async def run_harvest_closing_turn(
    *,
    conversation_id: str,
    execution_id: str,
) -> None:
    """Adopt the live execution and run a system closing CEO turn."""
    from agentcore.runtime.coordination.session import (
        active_coordination,
        adopt_active_execution,
    )

    session = active_coordination(execution_id)
    if session is None:
        logger.info(
            "coordination.harvest_no_session",
            conversation_id=conversation_id,
            execution_id=execution_id,
        )
        return
    if session.turn_attached:
        logger.info(
            "coordination.harvest_skipped_reattached",
            conversation_id=conversation_id,
            execution_id=execution_id,
        )
        return

    # Another turn already owns the conversation slot — let it adopt instead.
    existing = turn_runs.get(conversation_id)
    if existing is not None and not existing.task.done():
        logger.info(
            "coordination.harvest_deferred_live_turn",
            conversation_id=conversation_id,
            execution_id=execution_id,
        )
        return

    async with async_session_factory() as db:
        conv = await ConversationRepository(db).get_by_id_unscoped(conversation_id)
        if not conv:
            logger.warning(
                "coordination.harvest_conversation_missing",
                conversation_id=conversation_id,
                execution_id=execution_id,
            )
            return
        user_id = str(conv.user_id)
        folder_id = conv.folder_id
        local_binding = await resolve_local_binding(db, conv)
        profile_set = await resolve_profile_set(db, conv, user_id)
        memory_enabled = await resolve_memory_enabled(db, user_id)
        conversation_history_access = await resolve_conversation_history_access(db, user_id)
        permission_preset = await resolve_permission_preset(db, conversation_id)
        autonomy_policy = preset_to_autonomy(permission_preset)
        board = await BoardRepository(db).get_by_conversation_id(
            conversation_id, user_id=user_id
        )
        board_id = board.id if board else None
        from agentcore.db.repositories import MessageRepository

        await MessageRepository(db).create(
            conversation_id=conversation_id,
            role="user",
            content=_HARVEST_USER_TEXT,
            metadata={"origin": "execution_harvest", "execution_id": execution_id},
        )
        history = await load_chat_context(db, conversation_id, max_messages=40)

    sink = EventSink()
    backend = build_turn_backend(
        user_id=user_id,
        conversation_id=conversation_id,
        folder_id=folder_id,
        sink=sink,
        local_binding=local_binding,
    )

    async def _run() -> None:
        # Adopt before pipeline so CEO wait binds the live execution_id.
        adopt_active_execution(conversation_id, event_sink=sink)
        async with workspace_lock(
            workspace_storage_key(
                user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
            )
        ):
            await run_and_persist(
                conversation_id=conversation_id,
                user_message=_HARVEST_USER_TEXT,
                user_id=user_id,
                folder_id=folder_id,
                sink=sink,
                history=history[:-1] if history else [],
                attachments=None,
                backend=backend,
                llm_credentials=None,
                profile_set=profile_set,
                memory_enabled=memory_enabled,
                conversation_history_access=conversation_history_access,
                autonomy_policy=autonomy_policy,
                permission_preset=permission_preset,
                board_id=board_id,
                llm_supports_tools=None,
                x_client_platform=None,
            )
        await _notify_harvest_complete(
            user_id=user_id,
            conversation_id=conversation_id,
            execution_id=execution_id,
        )

    import asyncio

    task = asyncio.create_task(
        _run(),
        name=f"harvest-close-{execution_id[:8]}",
    )
    turn_runs.register(conversation_id=conversation_id, task=task, sink=sink)
    # Wait for the closing turn so the harvester can clear the registry afterward
    # if the turn never re-attached (edge failure).
    with contextlib.suppress(asyncio.CancelledError):
        await task
    logger.info(
        "coordination.harvest_closing_turn_done",
        conversation_id=conversation_id,
        execution_id=execution_id,
    )


async def _notify_harvest_complete(
    *,
    user_id: str,
    conversation_id: str,
    execution_id: str,
) -> None:
    with contextlib.suppress(Exception):
        await notify_user(
            user_id,
            PushNotification(
                title="团队任务已完成",
                body="后台团队已交付终稿，打开对话查看。",
                data={
                    "conversation_id": conversation_id,
                    "execution_id": execution_id,
                    "origin": "execution_harvest",
                },
            ),
        )
