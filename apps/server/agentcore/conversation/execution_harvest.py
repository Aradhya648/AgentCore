"""System-initiated harvest closing turn (异步团队产出投递 · 支柱 C).

When a detached coordination drive finishes, the harvester calls
:func:`run_harvest_closing_turn` to spawn a CEO turn that adopts the live
execution, consumes queued ``ALL_COMPLETED``, and delivers a final assistant
message. Meta stamps ``origin=execution_harvest`` for attribution.

Credential routing matches ordinary turns / standing-task fires (conversation
model selection + billing preflight) — never hardcode ``llm_credentials=None``
(that silently falls through to the platform key).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Literal

from agentcore.billing.gate import preflight_llm_credentials
from agentcore.conversation.common import (
    resolve_conversation_history_access,
    resolve_local_binding,
    resolve_memory_enabled,
    resolve_permission_axes,
    resolve_profile_set,
)
from agentcore.conversation.history import load_chat_context
from agentcore.conversation.turn_backend import build_turn_backend
from agentcore.conversation.turn_runner import run_and_persist
from agentcore.core.errors import AgentCoreError
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import (
    BoardRepository,
    ConversationRepository,
    CostEventRepository,
    UserRepository,
)
from agentcore.llm.resolve import (
    platform_llm_credentials,
    resolve_conversation_model_selection,
)
from agentcore.push import PushNotification, notify_user
from agentcore.runtime.events import EventSink
from agentcore.runtime.turn_runs import turn_runs
from agentcore.workspace.locate import workspace_storage_key
from agentcore.workspace.locks import workspace_lock

if TYPE_CHECKING:
    from agentcore.llm.credentials import LLMCredentials
    from agentcore.runtime.coordination.session import CoordinationSession

logger = get_logger(__name__)

HarvestKind = Literal["success", "failure", "cancelled"]

_HARVEST_USER_TEXT: dict[HarvestKind, str] = {
    "success": (
        "【系统收口】后台团队任务已全部完成。请综合队员产出，按终稿纪律交付给老板："
        "交付物在前，过程简述至多一段；勿粘贴协调事件原文。"
    ),
    "failure": (
        "【系统收口】后台团队任务已结束，但有队员失败。请综合已有产出与失败情况向老板交代："
        "交付物/缺口在前，失败原因简述至多一段；勿粘贴协调事件原文；勿假装全员成功。"
    ),
    "cancelled": (
        "【系统收口】后台团队任务已取消或中断。请基于已完成部分向老板简要收尾："
        "已交付与未完成清单在前，说明已取消；勿粘贴协调事件原文；勿宣称已全部完成。"
    ),
}

_HARVEST_PUSH: dict[HarvestKind, tuple[str, str]] = {
    "success": ("团队任务已完成", "后台团队已交付终稿，打开对话查看。"),
    "failure": ("团队任务有失败", "后台团队已结束但有失败，打开对话查看收尾。"),
    "cancelled": ("团队任务已取消", "后台团队已取消或中断，打开对话查看收尾。"),
}


class HarvestDeferredError(Exception):
    """Conversation slot occupied — keep registry; caller must retry, not unregister."""

    def __init__(self, conversation_id: str, execution_id: str) -> None:
        self.conversation_id = conversation_id
        self.execution_id = execution_id
        super().__init__(f"harvest deferred: live turn on {conversation_id}")


def harvest_closing_kind(session: CoordinationSession) -> HarvestKind:
    """Classify harvest outcome for synthetic user text (success / failure / cancelled)."""
    from agentcore.runtime.coordination.session import CoordinationEventKind

    if session.soft_stop:
        return "cancelled"
    if any(ev.kind is CoordinationEventKind.DRIVE_CANCELLED for ev in session._pending):
        return "cancelled"
    if session.failed_run_ids:
        return "failure"
    cancelled = (session.cancel_ids & session.completed_run_ids) - session.failed_run_ids
    if cancelled:
        return "cancelled"
    return "success"


def format_harvest_user_text(session: CoordinationSession) -> str:
    return _HARVEST_USER_TEXT[harvest_closing_kind(session)]


async def run_harvest_closing_turn(
    *,
    conversation_id: str,
    execution_id: str,
) -> None:
    """Adopt the live execution and run a system closing CEO turn.

    Raises:
        HarvestDeferredError: another turn owns the conversation slot — do **not**
            treat as success or clear the coordination registry.
    """
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

    # Another turn already owns the conversation slot — keep registry; retry later.
    existing = turn_runs.get(conversation_id)
    if existing is not None and not existing.task.done():
        logger.info(
            "coordination.harvest_deferred_live_turn",
            conversation_id=conversation_id,
            execution_id=execution_id,
        )
        raise HarvestDeferredError(conversation_id, execution_id)

    kind = harvest_closing_kind(session)
    user_text = _HARVEST_USER_TEXT[kind]

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
        user = await UserRepository(db).get_by_id(user_id)
        if user is None:
            logger.warning(
                "coordination.harvest_user_missing",
                conversation_id=conversation_id,
                execution_id=execution_id,
                user_id=user_id,
            )
            return
        try:
            selection = await resolve_conversation_model_selection(db, conv, user_id)
            llm_credentials: LLMCredentials | None = await preflight_llm_credentials(
                session=db,
                user=user,
                cost_repo=CostEventRepository(db),
                byok_missing_message=(
                    "系统收口需要可用的模型凭证，请先在「设置 · 模型配置」中填入 API Key。"
                ),
                model_origin=selection.origin,
                provider_id=selection.provider_id,
            )
            if selection.origin == "platform":
                llm_credentials = platform_llm_credentials(model=selection.model)
        except AgentCoreError as e:
            logger.warning(
                "coordination.harvest_credentials_unavailable",
                conversation_id=conversation_id,
                execution_id=execution_id,
                error=e.message or str(e),
                code=getattr(e, "code", None),
            )
            return
        local_binding = await resolve_local_binding(db, conv)
        profile_set = await resolve_profile_set(db, conv, user_id)
        memory_enabled = await resolve_memory_enabled(db, user_id)
        conversation_history_access = await resolve_conversation_history_access(db, user_id)
        permission_axes = await resolve_permission_axes(db, conversation_id)

        board = await BoardRepository(db).get_by_conversation_id(
            conversation_id, user_id=user_id
        )
        board_id = board.id if board else None
        from agentcore.db.repositories import MessageRepository

        await MessageRepository(db).create(
            conversation_id=conversation_id,
            role="user",
            content=user_text,
            metadata={
                "origin": "execution_harvest",
                "execution_id": execution_id,
                "harvest_kind": kind,
            },
        )
        history = await load_chat_context(db, conversation_id, max_messages=40)

    sink = EventSink()
    backend = await build_turn_backend(
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
                user_message=user_text,
                user_id=user_id,
                folder_id=folder_id,
                sink=sink,
                history=history[:-1] if history else [],
                attachments=None,
                backend=backend,
                llm_credentials=llm_credentials,
                profile_set=profile_set,
                memory_enabled=memory_enabled,
                conversation_history_access=conversation_history_access,
                permission_axes=permission_axes,
                board_id=board_id,
                llm_supports_tools=None,
                x_client_platform=None,
            )
        await _notify_harvest_complete(
            user_id=user_id,
            conversation_id=conversation_id,
            execution_id=execution_id,
            kind=kind,
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
        harvest_kind=kind,
    )


async def _notify_harvest_complete(
    *,
    user_id: str,
    conversation_id: str,
    execution_id: str,
    kind: HarvestKind = "success",
) -> None:
    title, body = _HARVEST_PUSH[kind]
    with contextlib.suppress(Exception):
        await notify_user(
            user_id,
            PushNotification(
                title=title,
                body=body,
                data={
                    "conversation_id": conversation_id,
                    "execution_id": execution_id,
                    "origin": "execution_harvest",
                    "harvest_kind": kind,
                },
            ),
        )
