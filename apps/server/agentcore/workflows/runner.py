"""Dispatch + run a user workflow via the direct-start pipeline (no CEO 编队)."""

from __future__ import annotations

from agentcore.billing.gate import preflight_llm_credentials
from agentcore.conversation.background import spawn_background
from agentcore.conversation.common import (
    default_permission_axes_for_user,
    resolve_conversation_history_access,
    resolve_memory_enabled,
    resolve_permission_axes,
    resolve_profile_set,
)
from agentcore.conversation.history import load_chat_context
from agentcore.conversation.turn_backend import build_turn_backend
from agentcore.core.errors import AgentCoreError
from agentcore.core.logging import get_logger
from agentcore.core.types import PermissionAxes
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import (
    ConversationRepository,
    CostEventRepository,
    FolderRepository,
    MessageRepository,
    UserRepository,
)
from agentcore.llm.resolve import (
    platform_llm_credentials,
    resolve_conversation_model_selection,
)
from agentcore.runtime.events import EventSink
from agentcore.workflows.definition import (
    WorkflowDefinitionError,
    expand_workflow_to_tasks,
)
from agentcore.workspace.locate import workspace_storage_key
from agentcore.workspace.locks import workspace_lock

logger = get_logger(__name__)


def build_workflow_user_message(*, workflow_name: str, note: str | None = None) -> str:
    """User-visible kickoff line for a workflow direct-start turn."""
    base = f"按工作流「{workflow_name}」执行。"
    cleaned = (note or "").strip()
    if cleaned:
        return f"{base}\n\n本轮补充：\n{cleaned}"
    return base


async def dispatch_workflow_run(
    *,
    user_id: str,
    workflow_id: str,
    workflow_version: int,
    definition: dict,
    folder_id: str,
    note: str | None = None,
    conversation_id: str | None = None,
    workflow_name: str = "工作流",
    permission_axes: dict | None = None,
) -> str:
    """Validate definition, ensure conversation, spawn background job. Returns conversation id."""
    try:
        tasks = expand_workflow_to_tasks(definition)
    except WorkflowDefinitionError as e:
        raise ValueError(str(e)) from e
    if not tasks:
        raise ValueError("工作流没有可执行的队员步骤")

    async with async_session_factory() as session:
        folder = await FolderRepository(session).get_by_id(folder_id, user_id=user_id)
        if folder is None:
            raise LookupError("工作区不存在")
        axes = permission_axes
        if axes is None:
            axes = (await default_permission_axes_for_user(session, user_id)).to_dict()
        conv_id = conversation_id
        if conv_id:
            conv = await ConversationRepository(session).get_by_id(
                conv_id, user_id=user_id
            )
            if conv is None:
                raise LookupError("对话不存在")
            if conv.folder_id and conv.folder_id != folder_id:
                raise ValueError("对话不属于所选工作区")
        else:
            conv = await ConversationRepository(session).create(
                user_id=user_id,
                title=workflow_name,
                folder_id=folder_id,
                mode="workflow",
                permission_axes=PermissionAxes.from_mapping(axes).to_dict(),
            )
            conv_id = conv.id

    spawn_background(
        run_workflow_job(
            conversation_id=conv_id,
            user_id=user_id,
            folder_id=folder_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
            workflow_name=workflow_name,
            tasks=tasks,
            note=note,
        )
    )
    return conv_id


async def run_workflow_job(
    *,
    conversation_id: str,
    user_id: str,
    folder_id: str,
    workflow_id: str,
    workflow_version: int,
    workflow_name: str,
    tasks: list[dict],
    note: str | None = None,
) -> None:
    """Background: persist user message + run workflow direct-start pipeline."""
    sink = EventSink()
    try:
        user_message = build_workflow_user_message(workflow_name=workflow_name, note=note)
        async with async_session_factory() as session:
            user = await UserRepository(session).get_by_id(user_id)
            if user is None:
                logger.error("workflow.run_user_missing", user_id=user_id)
                return
            conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
            if conv is None:
                logger.error(
                    "workflow.run_conversation_missing",
                    conversation_id=conversation_id,
                )
                return
            try:
                selection = await resolve_conversation_model_selection(
                    session, conv, user_id
                )
                credentials = await preflight_llm_credentials(
                    session=session,
                    user=user,
                    cost_repo=CostEventRepository(session),
                    byok_missing_message="跑工作流需要可用的模型凭证，请先在设置中配置。",
                    model_origin=selection.origin,
                    provider_id=selection.provider_id,
                )
                if selection.origin == "platform":
                    credentials = platform_llm_credentials(model=selection.model)
            except AgentCoreError as e:
                logger.warning(
                    "workflow.run_credentials_failed",
                    conversation_id=conversation_id,
                    error=e.message or str(e),
                )
                return
            profile_set = await resolve_profile_set(session, conv, user_id)
            memory_enabled = await resolve_memory_enabled(session, user_id)
            conversation_history_access = await resolve_conversation_history_access(
                session, user_id
            )
            axes = await resolve_permission_axes(session, conversation_id)

        backend = await build_turn_backend(
            user_id=user_id,
            conversation_id=conversation_id,
            folder_id=folder_id,
            sink=sink,
            local_binding=None,
        )

        async with workspace_lock(
            workspace_storage_key(
                user_id=user_id, folder_id=folder_id, conversation_id=conversation_id
            )
        ):
            async with async_session_factory() as session:
                await MessageRepository(session).create(
                    conversation_id=conversation_id,
                    role="user",
                    content=user_message,
                )
                history = await load_chat_context(session, conversation_id, max_messages=40)

            from agentcore.conversation.turn_runner import (
                session_callbacks,
                suspension_callbacks,
            )
            from agentcore.runtime.pipeline.workflow_run import run_workflow_pipeline

            session_saver, session_loader = session_callbacks(conversation_id)
            suspension_saver, suspension_deleter = suspension_callbacks()
            await run_workflow_pipeline(
                conversation_id=conversation_id,
                user_id=user_id,
                user_message=user_message,
                tasks=tasks,
                workflow_id=workflow_id,
                workflow_version=workflow_version,
                sink=sink,
                backend=backend,
                history=history[:-1],
                folder_id=folder_id,
                memory_enabled=memory_enabled,
                conversation_history_access=conversation_history_access,
                permission_axes=axes,
                profile_set=profile_set,
                llm_credentials=credentials,
                session_saver=session_saver,
                session_loader=session_loader,
                suspension_saver=suspension_saver,
                suspension_deleter=suspension_deleter,
            )
        logger.info(
            "workflow.run_finished",
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            workflow_version=workflow_version,
        )
    except Exception as e:
        logger.error(
            "workflow.run_failed",
            conversation_id=conversation_id,
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
    finally:
        if not sink._closed:
            sink.close()
