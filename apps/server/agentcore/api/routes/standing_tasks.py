"""Standing tasks + inbox + L2a webhook hook routes."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request

from agentcore.api.dependencies import (
    AuthUser,
    get_folder_repo,
    get_standing_task_repo,
    get_standing_task_run_repo,
)
from agentcore.api.schemas import StatusResponse
from agentcore.api.schemas.standing_tasks import (
    CreateStandingTaskRequest,
    RotateWebhookSecretResponse,
    StandingTaskRunListResponse,
    StandingTaskRunSummary,
    StandingTaskSummary,
    TriggerStandingTaskResponse,
    UpdateStandingTaskRequest,
)
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.core.types import DEFAULT_PERMISSION_AXES, new_id
from agentcore.db.repositories import FolderRepository
from agentcore.db.repositories.standing_tasks import (
    StandingTaskRepository,
    StandingTaskRunRepository,
)
from agentcore.standing_tasks.paths import webhook_path
from agentcore.standing_tasks.runner import dispatch_standing_task
from agentcore.standing_tasks.schedule import CronError, next_run_after, resolve_cron
from agentcore.standing_tasks.webhook import (
    enforce_webhook_rate_limit,
    extract_event_text,
    generate_webhook_secret,
    idempotency_lookup,
    idempotency_store,
    require_webhook_secret,
)

router = APIRouter(tags=["standing-tasks"])
hooks_router = APIRouter(prefix="/hooks", tags=["standing-hooks"])


def _require_cloud_folder(folder) -> None:
    if folder is None:
        raise NotFoundError("工作区不存在")
    if folder.local_root_id:
        raise ValidationError("站立任务仅支持云工作区（拒绝本地 folder）")


@router.post("/standing-tasks", response_model=StandingTaskSummary, status_code=201)
async def create_standing_task(
    body: CreateStandingTaskRequest,
    user: AuthUser,
    folders: FolderRepository = Depends(get_folder_repo),
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
):
    folder = await folders.get_by_id(body.folder_id, user_id=user.user_id)
    _require_cloud_folder(folder)
    axes = (
        body.permission_axes.to_axes().to_dict()
        if body.permission_axes is not None
        else DEFAULT_PERMISSION_AXES.to_dict()
    )
    plaintext_secret: str | None = None
    if body.trigger_kind == "webhook":
        plaintext_secret, secret_hash = generate_webhook_secret()
        row = await repo.create(
            user_id=user.user_id,
            folder_id=body.folder_id,
            name=body.name,
            goal=body.goal,
            cron=None,
            permission_axes=axes,
            next_run_at=None,
            enabled=body.enabled,
            trigger_kind="webhook",
            webhook_id=new_id(),
            webhook_secret_hash=secret_hash,
        )
        return StandingTaskSummary.from_row(row, webhook_secret=plaintext_secret)

    try:
        cron = resolve_cron(cron=body.cron, preset=body.schedule_preset)
        next_at = next_run_after(cron, datetime.now(UTC))
    except CronError as e:
        raise ValidationError(str(e)) from e
    row = await repo.create(
        user_id=user.user_id,
        folder_id=body.folder_id,
        name=body.name,
        goal=body.goal,
        cron=cron,
        permission_axes=axes,
        next_run_at=next_at,
        enabled=body.enabled,
        trigger_kind="schedule",
    )
    return StandingTaskSummary.from_row(row)


@router.get("/standing-tasks", response_model=list[StandingTaskSummary])
async def list_standing_tasks(
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
):
    rows = await repo.list_by_user(user.user_id)
    return [StandingTaskSummary.from_row(r) for r in rows]


@router.get("/standing-tasks/{task_id}", response_model=StandingTaskSummary)
async def get_standing_task(
    task_id: str,
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
):
    row = await repo.get_by_id(task_id, user_id=user.user_id)
    if row is None:
        raise NotFoundError("站立任务不存在")
    return StandingTaskSummary.from_row(row)


@router.patch("/standing-tasks/{task_id}", response_model=StandingTaskSummary)
async def update_standing_task(
    task_id: str,
    body: UpdateStandingTaskRequest,
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
):
    existing = await repo.get_by_id(task_id, user_id=user.user_id)
    if existing is None:
        raise NotFoundError("站立任务不存在")

    fields = body.model_fields_set
    kwargs: dict = {}
    if "name" in fields:
        kwargs["name"] = body.name
    if "goal" in fields:
        kwargs["goal"] = body.goal
    if "enabled" in fields:
        kwargs["enabled"] = body.enabled
    if "permission_axes" in fields and body.permission_axes is not None:
        kwargs["permission_axes"] = body.permission_axes.to_axes().to_dict()

    plaintext_secret: str | None = None
    target_kind = body.trigger_kind if "trigger_kind" in fields else existing.trigger_kind

    if "trigger_kind" in fields and body.trigger_kind != existing.trigger_kind:
        if body.trigger_kind == "webhook":
            # Switch schedule → webhook: clear cron clock, mint webhook identity.
            plaintext_secret, secret_hash = generate_webhook_secret()
            kwargs.update(
                {
                    "trigger_kind": "webhook",
                    "cron": None,
                    "next_run_at": None,
                    "webhook_id": new_id(),
                    "webhook_secret_hash": secret_hash,
                }
            )
        else:
            # Switch webhook → schedule: wipe webhook; require cron/preset.
            if "cron" not in fields and "schedule_preset" not in fields and "preset" not in fields:
                raise ValidationError("切换到定时触发时须提供 schedule_preset 或 cron")
            try:
                cron = resolve_cron(cron=body.cron, preset=body.schedule_preset)
                next_at = next_run_after(cron, datetime.now(UTC))
            except CronError as e:
                raise ValidationError(str(e)) from e
            kwargs.update(
                {
                    "trigger_kind": "schedule",
                    "cron": cron,
                    "next_run_at": next_at,
                    "webhook_id": None,
                    "webhook_secret_hash": None,
                }
            )
    elif target_kind == "schedule" and (
        "cron" in fields or "schedule_preset" in fields or "preset" in fields
    ):
        try:
            cron = resolve_cron(cron=body.cron, preset=body.schedule_preset)
            kwargs["cron"] = cron
            kwargs["next_run_at"] = next_run_after(cron, datetime.now(UTC))
        except CronError as e:
            raise ValidationError(str(e)) from e
    elif target_kind == "webhook" and (
        "cron" in fields or "schedule_preset" in fields or "preset" in fields
    ):
        raise ValidationError("webhook 任务不可设置 cron / schedule_preset")

    row = await repo.update(task_id, user_id=user.user_id, **kwargs)
    if row is None:
        raise NotFoundError("站立任务不存在")
    return StandingTaskSummary.from_row(row, webhook_secret=plaintext_secret)


@router.delete("/standing-tasks/{task_id}", response_model=StatusResponse)
async def delete_standing_task(
    task_id: str,
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
):
    ok = await repo.delete(task_id, user_id=user.user_id)
    if not ok:
        raise NotFoundError("站立任务不存在")
    return StatusResponse()


@router.post(
    "/standing-tasks/{task_id}/run",
    response_model=TriggerStandingTaskResponse,
    status_code=202,
)
async def trigger_standing_task(
    task_id: str,
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
    folders: FolderRepository = Depends(get_folder_repo),
):
    """立即跑一次（验收 / 收件箱重跑）。不推进 cron 时钟。"""
    task = await repo.get_by_id(task_id, user_id=user.user_id)
    if task is None:
        raise NotFoundError("站立任务不存在")
    folder = await folders.get_by_id(task.folder_id, user_id=user.user_id)
    _require_cloud_folder(folder)
    run_id = await dispatch_standing_task(
        task_id=task_id,
        user_id=user.user_id,
        advance_schedule=False,
        trigger_source="manual",
    )
    return TriggerStandingTaskResponse(run_id=run_id)


@router.post(
    "/standing-tasks/{task_id}/rotate-webhook-secret",
    response_model=RotateWebhookSecretResponse,
)
async def rotate_webhook_secret(
    task_id: str,
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
):
    task = await repo.get_by_id(task_id, user_id=user.user_id)
    if task is None:
        raise NotFoundError("站立任务不存在")
    if task.trigger_kind != "webhook" or not task.webhook_id:
        raise ValidationError("仅 webhook 站立任务可轮换密钥")
    plaintext, secret_hash = generate_webhook_secret()
    row = await repo.update(
        task_id,
        user_id=user.user_id,
        webhook_secret_hash=secret_hash,
    )
    if row is None or not row.webhook_id:
        raise NotFoundError("站立任务不存在")
    return RotateWebhookSecretResponse(
        webhook_id=row.webhook_id,
        webhook_url=webhook_path(row.webhook_id),
        webhook_secret=plaintext,
    )


@router.get("/standing-task-runs", response_model=StandingTaskRunListResponse)
async def list_standing_task_runs(
    user: AuthUser,
    status: Literal["running", "succeeded", "failed", "awaiting_user"] | None = Query(None),
    unacked: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    repo: StandingTaskRunRepository = Depends(get_standing_task_run_repo),
):
    items = await repo.list_for_user(
        user.user_id, status=status, limit=limit, unacked_only=unacked
    )
    badge = await repo.count_badge(user.user_id)
    return StandingTaskRunListResponse(
        items=[StandingTaskRunSummary.model_validate(r) for r in items],
        badge=badge,
    )


@router.post("/standing-task-runs/{run_id}/ack", response_model=StandingTaskRunSummary)
async def ack_standing_task_run(
    run_id: str,
    user: AuthUser,
    repo: StandingTaskRunRepository = Depends(get_standing_task_run_repo),
):
    row = await repo.ack(run_id, user_id=user.user_id)
    if row is None:
        raise NotFoundError("收件箱条目不存在")
    return StandingTaskRunSummary.model_validate(row)


@hooks_router.post(
    "/standing/{webhook_id}",
    response_model=TriggerStandingTaskResponse,
    status_code=202,
)
async def fire_standing_webhook(
    webhook_id: str,
    request: Request,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
    folders: FolderRepository = Depends(get_folder_repo),
    authorization: str | None = Header(None),
    x_agentcore_webhook_secret: str | None = Header(
        None, alias="X-AgentCore-Webhook-Secret"
    ),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
):
    """Public webhook fire — no user JWT; auth via shared secret header."""
    task = await repo.get_by_webhook_id(webhook_id)
    if task is None:
        raise NotFoundError("Webhook 不存在")
    require_webhook_secret(
        authorization=authorization,
        x_webhook_secret=x_agentcore_webhook_secret,
        expected_hash=task.webhook_secret_hash,
    )
    if not task.enabled:
        raise ValidationError("站立任务已停用")

    idem_key = (x_idempotency_key or "").strip() or None
    if idem_key:
        prior = idempotency_lookup(webhook_id, idem_key)
        if prior is not None:
            return TriggerStandingTaskResponse(run_id=prior)

    enforce_webhook_rate_limit(task.id)

    folder = await folders.get_by_id(task.folder_id, user_id=task.user_id)
    _require_cloud_folder(folder)

    body = await request.body()
    event_text = extract_event_text(body, content_type=request.headers.get("content-type"))

    run_id = await dispatch_standing_task(
        task_id=task.id,
        user_id=task.user_id,
        advance_schedule=False,
        event_text=event_text or None,
        trigger_source="webhook",
    )
    if idem_key:
        idempotency_store(webhook_id, idem_key, run_id)
    return TriggerStandingTaskResponse(run_id=run_id)
