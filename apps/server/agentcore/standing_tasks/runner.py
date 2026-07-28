"""Execute one standing-task fire (代跑, approvals_enabled=True).

Shape mirrors ``handoff_jobs`` (spawn_background + credentials) but does **not**
reuse handoff tables/semantics. Pause truth stays in ``paused_turns``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agentcore.billing.gate import preflight_llm_credentials
from agentcore.conversation.background import spawn_background
from agentcore.conversation.common import (
    resolve_conversation_history_access,
    resolve_memory_enabled,
    resolve_permission_axes,
    resolve_profile_set,
)
from agentcore.conversation.history import load_chat_context
from agentcore.conversation.turn_backend import build_turn_backend
from agentcore.conversation.turn_runner import run_and_persist
from agentcore.core.errors import AgentCoreError
from agentcore.core.logging import get_logger
from agentcore.core.types import PermissionAxes
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import (
    ConversationRepository,
    CostEventRepository,
    FolderRepository,
    MessageRepository,
    PausedTurnRepository,
    UserRepository,
)
from agentcore.db.repositories.standing_tasks import (
    StandingTaskRepository,
    StandingTaskRunRepository,
)
from agentcore.llm.resolve import (
    platform_llm_credentials,
    resolve_conversation_model_selection,
)
from agentcore.runtime.events import EventSink, FinishReason
from agentcore.standing_tasks.schedule import next_run_after
from agentcore.standing_tasks.webhook import build_fire_message
from agentcore.workspace.locate import workspace_storage_key
from agentcore.workspace.locks import workspace_lock

logger = get_logger(__name__)

_SUMMARY_MAX = 500


def _truncate_summary(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text.strip()
    if len(cleaned) <= _SUMMARY_MAX:
        return cleaned
    return cleaned[: _SUMMARY_MAX - 1] + "…"


def _finish_is_paused(finish: object) -> bool:
    if finish is FinishReason.PAUSED:
        return True
    return getattr(finish, "value", finish) == "paused"


async def _ensure_pinned_conversation(
    *,
    task_id: str,
    user_id: str,
    folder_id: str,
    name: str,
    permission_axes: dict,
) -> str:
    """Return the pinned conversation id, creating one on first fire."""
    async with async_session_factory() as session:
        tasks = StandingTaskRepository(session)
        task = await tasks.get_by_id(task_id)
        if task is None:
            raise RuntimeError(f"standing task gone: {task_id}")
        if task.conversation_id:
            return task.conversation_id
        axes = PermissionAxes.from_mapping(permission_axes).to_dict()
        conv = await ConversationRepository(session).create(
            user_id=user_id,
            title=name,
            folder_id=folder_id,
            mode="standing",
            permission_axes=axes,
        )
        await tasks.attach_conversation(task_id, conversation_id=conv.id)
        return conv.id


async def run_standing_task_job(
    *,
    run_id: str,
    task_id: str,
    lease_owner: str | None = None,
    advance_schedule: bool = True,
    event_text: str | None = None,
) -> None:
    """Run one claimed standing-task fire end-to-end."""
    sink = EventSink()
    conversation_id: str | None = None
    try:
        async with async_session_factory() as session:
            task = await StandingTaskRepository(session).get_by_id(task_id)
            if task is None:
                await StandingTaskRunRepository(session).mark_failed(
                    run_id, error="站立任务不存在"
                )
                return
            if not task.enabled and advance_schedule:
                # Disabled after claim (race) — abort without advancing further.
                await StandingTaskRunRepository(session).mark_failed(
                    run_id, error="站立任务已停用"
                )
                return
            user_id = task.user_id
            folder_id = task.folder_id
            goal = task.goal
            name = task.name
            permission_axes = dict(task.permission_axes or {})
            cron = task.cron
            trigger_kind = getattr(task, "trigger_kind", None) or "schedule"
            # Cloud folder guard (defense in depth; create already rejects local).
            folder = await FolderRepository(session).get_by_id(folder_id, user_id=user_id)
            if folder is None or folder.local_root_id:
                await StandingTaskRunRepository(session).mark_failed(
                    run_id, error="站立任务仅支持云工作区"
                )
                return

        user_message = build_fire_message(goal=goal, event_text=event_text)

        conversation_id = await _ensure_pinned_conversation(
            task_id=task_id,
            user_id=user_id,
            folder_id=folder_id,
            name=name,
            permission_axes=permission_axes,
        )

        async with async_session_factory() as session:
            user = await UserRepository(session).get_by_id(user_id)
            if user is None:
                await StandingTaskRunRepository(session).mark_failed(
                    run_id, error="用户不存在"
                )
                return
            conv = await ConversationRepository(session).get_by_id_unscoped(conversation_id)
            if conv is None:
                await StandingTaskRunRepository(session).mark_failed(
                    run_id, error="绑定对话不存在"
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
                    byok_missing_message="站立任务代跑需要可用的模型凭证，请先在设置中配置。",
                    model_origin=selection.origin,
                    provider_id=selection.provider_id,
                )
                if selection.origin == "platform":
                    credentials = platform_llm_credentials(model=selection.model)
            except AgentCoreError as e:
                await StandingTaskRunRepository(session).mark_failed(
                    run_id, error=e.message or str(e)
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
                user_msg = await MessageRepository(session).create(
                    conversation_id=conversation_id,
                    role="user",
                    content=user_message,
                )
                history = await load_chat_context(session, conversation_id, max_messages=40)
                await StandingTaskRunRepository(session).set_conversation_and_message(
                    run_id,
                    conversation_id=conversation_id,
                    user_message_id=user_msg.id,
                )

            # Monkeypatch seam for unit tests (see test_standing_tasks.py).
            result = await _run_pipeline(
                conversation_id=conversation_id,
                user_message=user_message,
                user_id=user_id,
                folder_id=folder_id,
                sink=sink,
                history=history[:-1],
                backend=backend,
                llm_credentials=credentials,
                profile_set=profile_set,
                memory_enabled=memory_enabled,
                conversation_history_access=conversation_history_access,
                permission_axes=axes,
            )

        finish = (result or {}).get("finish_reason") if isinstance(result, dict) else None
        summary = _truncate_summary(
            (result or {}).get("content") if isinstance(result, dict) else None
        )
        paused = False

        async with async_session_factory() as session:
            paused = await PausedTurnRepository(session).exists_for_conversation(
                conversation_id
            )
            runs = StandingTaskRunRepository(session)
            if paused or _finish_is_paused(finish):
                await runs.mark_awaiting_user(run_id, summary=summary)
            elif isinstance(result, dict) and (
                result.get("error")
                or getattr(finish, "value", finish) in ("error", "cancelled")
            ):
                await runs.mark_failed(
                    run_id, error=str(result.get("error") or "回合失败")
                )
            else:
                # Prefer assistant content from DB when pipeline result lacked it.
                if not summary:
                    recent = await MessageRepository(session).list_recent(
                        conversation_id, limit=1
                    )
                    if recent and recent[0].role == "assistant":
                        summary = _truncate_summary(recent[0].content)
                await runs.mark_succeeded(run_id, summary=summary)

            # Only advance cron for schedule triggers that still have a cron expression.
            if advance_schedule and trigger_kind == "schedule" and cron:
                try:
                    nxt = next_run_after(cron, datetime.now(UTC))
                    await StandingTaskRepository(session).advance_next_run(
                        task_id, next_run_at=nxt
                    )
                except Exception as e:  # noqa: BLE001 — schedule math must not hide run status
                    logger.warning(
                        "standing_task.next_run_failed",
                        task_id=task_id,
                        error=str(e),
                    )

        logger.info(
            "standing_task.run_finished",
            run_id=run_id,
            task_id=task_id,
            conversation_id=conversation_id,
            paused=bool(paused) if conversation_id else False,
        )
    except Exception as e:
        logger.error(
            "standing_task.run_failed",
            run_id=run_id,
            task_id=task_id,
            error=str(e),
            exc_info=True,
        )
        async with async_session_factory() as session:
            await StandingTaskRunRepository(session).mark_failed(run_id, error=str(e))
    finally:
        if lease_owner is not None:
            async with async_session_factory() as session:
                await StandingTaskRepository(session).clear_lease(
                    task_id, owner=lease_owner
                )
        if not sink._closed:
            sink.close()


async def _run_pipeline(**kwargs):
    """Run the chat turn. Returns a result dict when the test seam patches it;
    production path uses ``run_and_persist`` (returns None) and status is inferred
    from ``paused_turns`` / latest assistant message.
    """
    # Production: full persist path (suspension + cost + journal).
    await run_and_persist(
        conversation_id=kwargs["conversation_id"],
        user_message=kwargs["user_message"],
        user_id=kwargs["user_id"],
        folder_id=kwargs["folder_id"],
        sink=kwargs["sink"],
        history=kwargs["history"],
        attachments=None,
        backend=kwargs["backend"],
        llm_credentials=kwargs["llm_credentials"],
        profile_set=kwargs.get("profile_set"),
        memory_enabled=kwargs.get("memory_enabled", True),
        conversation_history_access=kwargs.get("conversation_history_access", True),
        permission_axes=kwargs.get("permission_axes"),
    )
    return None


def spawn_standing_task_run(
    *,
    run_id: str,
    task_id: str,
    lease_owner: str | None = None,
    advance_schedule: bool = True,
    event_text: str | None = None,
) -> None:
    """Fire-and-forget a standing-task job."""
    spawn_background(
        run_standing_task_job(
            run_id=run_id,
            task_id=task_id,
            lease_owner=lease_owner,
            advance_schedule=advance_schedule,
            event_text=event_text,
        )
    )


async def dispatch_standing_task(
    *,
    task_id: str,
    user_id: str,
    advance_schedule: bool = False,
    lease_owner: str | None = None,
    event_text: str | None = None,
    trigger_source: str = "manual",
) -> str:
    """Create a running inbox row and spawn the job. Returns ``run_id``.

    Used by the scheduler (``advance_schedule=True``), webhook hook, and the
    manual「立即跑一次」endpoint (``advance_schedule=False`` so the cron clock
    is untouched).

    Task-level mutex: when ``lease_owner`` is omitted (webhook / manual), claims
    the existing lease columns before spawning. An unexpired lease →
    ``ConflictError`` (HTTP 409) — never a silent second run. The scheduler
    path already claimed via ``claim_due`` and passes ``lease_owner``.
    """
    from uuid import uuid4

    from agentcore.config import settings
    from agentcore.core.errors import ConflictError

    claimed_owner = lease_owner
    async with async_session_factory() as session:
        tasks = StandingTaskRepository(session)
        task = await tasks.get_by_id(task_id, user_id=user_id)
        if task is None:
            raise LookupError("standing task not found")
        # Capture before claim commit (expire_on_commit may detach the row).
        pinned_conversation_id = task.conversation_id

        if claimed_owner is None:
            claimed_owner = f"dispatch-{uuid4().hex[:12]}"
            claimed = await tasks.claim_dispatch(
                task_id,
                owner=claimed_owner,
                lease_seconds=settings.standing_task_lease_seconds,
            )
            if claimed is None:
                raise ConflictError("站立任务正在执行中，请稍后再试")

        try:
            run = await StandingTaskRunRepository(session).create(
                standing_task_id=task_id,
                user_id=user_id,
                conversation_id=pinned_conversation_id,
                status="running",
                trigger_source=trigger_source,
            )
            run_id = run.id
        except Exception:
            if lease_owner is None and claimed_owner is not None:
                await tasks.clear_lease(task_id, owner=claimed_owner)
            raise

    spawn_standing_task_run(
        run_id=run_id,
        task_id=task_id,
        lease_owner=claimed_owner,
        advance_schedule=advance_schedule,
        event_text=event_text,
    )
    return run_id
