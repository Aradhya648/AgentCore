"""Standing tasks + inbox + L2a webhook hook routes + system templates."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request

from agentcore.api.dependencies import (
    AuthUser,
    get_folder_repo,
    get_standing_task_repo,
    get_standing_task_run_repo,
    get_user_workflow_repo,
)
from agentcore.api.schemas import StatusResponse
from agentcore.api.schemas.standing_tasks import (
    CreateStandingTaskRequest,
    EnsureStandingTaskTemplateRequest,
    RotateWebhookSecretResponse,
    StandingTaskRunListResponse,
    StandingTaskRunSummary,
    StandingTaskSummary,
    StandingTaskTemplateSummary,
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
from agentcore.db.repositories.user_workflows import UserWorkflowRepository
from agentcore.standing_tasks.paths import webhook_path
from agentcore.standing_tasks.runner import dispatch_standing_task
from agentcore.standing_tasks.schedule import CronError, next_run_after, resolve_cron
from agentcore.standing_tasks.templates import (
    DAILY_CONVERSATION_REVIEW,
    DEFAULT_TEMPLATE_AXES,
    daily_review_goal,
    is_known_template,
    list_catalog,
    normalize_template_config,
)
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


async def _resolve_workflow_name(
    workflows: UserWorkflowRepository,
    *,
    user_id: str,
    workflow_id: str | None,
) -> str | None:
    if not workflow_id:
        return None
    row = await workflows.get_by_id(workflow_id, user_id=user_id)
    return row.name if row is not None else None


async def _require_owned_workflow(
    workflows: UserWorkflowRepository,
    *,
    user_id: str,
    workflow_id: str,
) -> None:
    row = await workflows.get_by_id(workflow_id, user_id=user_id)
    if row is None:
        raise NotFoundError("工作流不存在")


async def _summary(
    row,
    *,
    user_id: str,
    workflows: UserWorkflowRepository,
    webhook_secret: str | None = None,
) -> StandingTaskSummary:
    name = await _resolve_workflow_name(
        workflows, user_id=user_id, workflow_id=getattr(row, "workflow_id", None)
    )
    return StandingTaskSummary.from_row(
        row, webhook_secret=webhook_secret, workflow_name=name
    )


async def _validate_template_folder_ids(
    folders: FolderRepository,
    *,
    user_id: str,
    folder_ids: list[str],
) -> None:
    for fid in folder_ids:
        folder = await folders.get_by_id(fid, user_id=user_id)
        _require_cloud_folder(folder)


@router.get(
    "/standing-task-templates",
    response_model=list[StandingTaskTemplateSummary],
)
async def list_standing_task_templates(
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
):
    out: list[StandingTaskTemplateSummary] = []
    for item in list_catalog():
        row = await repo.get_by_template_key(user.user_id, item.key)
        out.append(
            StandingTaskTemplateSummary(
                key=item.key,
                title=item.title,
                description=item.description,
                default_name=item.default_name,
                default_cron=item.default_cron,
                installed_task_id=row.id if row else None,
                enabled=row.enabled if row else None,
            )
        )
    return out


@router.post(
    "/standing-task-templates/{template_key}/ensure",
    response_model=StandingTaskSummary,
)
async def ensure_standing_task_template(
    template_key: str,
    body: EnsureStandingTaskTemplateRequest,
    user: AuthUser,
    folders: FolderRepository = Depends(get_folder_repo),
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
    workflows: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    """Idempotent install of a system template. Default enabled=false (引导开)."""
    if not is_known_template(template_key):
        raise NotFoundError("未知系统模板")
    existing = await repo.get_by_template_key(user.user_id, template_key)
    if existing is not None:
        return await _summary(existing, user_id=user.user_id, workflows=workflows)

    folder = await folders.get_by_id(body.folder_id, user_id=user.user_id)
    _require_cloud_folder(folder)
    cfg = normalize_template_config(
        body.template_config.model_dump() if body.template_config else None
    )
    await _validate_template_folder_ids(
        folders, user_id=user.user_id, folder_ids=list(cfg["folder_ids"])
    )

    catalog = next(i for i in list_catalog() if i.key == template_key)
    try:
        if body.cron is None and body.schedule_preset is None:
            cron = resolve_cron(cron=catalog.default_cron)
        else:
            cron = resolve_cron(cron=body.cron, preset=body.schedule_preset)
        next_at = next_run_after(cron, datetime.now(UTC))
    except CronError as e:
        raise ValidationError(str(e)) from e

    axes = (
        body.permission_axes.to_axes().to_dict()
        if body.permission_axes is not None
        else dict(DEFAULT_TEMPLATE_AXES)
    )
    goal = (
        daily_review_goal()
        if template_key == DAILY_CONVERSATION_REVIEW
        else catalog.title
    )
    row = await repo.create(
        user_id=user.user_id,
        folder_id=body.folder_id,
        name=catalog.default_name,
        goal=goal,
        cron=cron,
        permission_axes=axes,
        next_run_at=next_at,
        enabled=body.enabled,
        trigger_kind="schedule",
        template_key=template_key,
        template_config=cfg,
    )
    return await _summary(row, user_id=user.user_id, workflows=workflows)


@router.post("/standing-tasks", response_model=StandingTaskSummary, status_code=201)
async def create_standing_task(
    body: CreateStandingTaskRequest,
    user: AuthUser,
    folders: FolderRepository = Depends(get_folder_repo),
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
    workflows: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    folder = await folders.get_by_id(body.folder_id, user_id=user.user_id)
    _require_cloud_folder(folder)
    if body.workflow_id:
        await _require_owned_workflow(
            workflows, user_id=user.user_id, workflow_id=body.workflow_id
        )
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
            goal=body.goal or "",
            cron=None,
            permission_axes=axes,
            next_run_at=None,
            enabled=body.enabled,
            trigger_kind="webhook",
            webhook_id=new_id(),
            webhook_secret_hash=secret_hash,
            workflow_id=body.workflow_id,
        )
        return await _summary(
            row,
            user_id=user.user_id,
            workflows=workflows,
            webhook_secret=plaintext_secret,
        )

    try:
        cron = resolve_cron(cron=body.cron, preset=body.schedule_preset)
        next_at = next_run_after(cron, datetime.now(UTC))
    except CronError as e:
        raise ValidationError(str(e)) from e
    row = await repo.create(
        user_id=user.user_id,
        folder_id=body.folder_id,
        name=body.name,
        goal=body.goal or "",
        cron=cron,
        permission_axes=axes,
        next_run_at=next_at,
        enabled=body.enabled,
        trigger_kind="schedule",
        workflow_id=body.workflow_id,
    )
    return await _summary(row, user_id=user.user_id, workflows=workflows)


@router.get("/standing-tasks", response_model=list[StandingTaskSummary])
async def list_standing_tasks(
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
    workflows: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    rows = await repo.list_by_user(user.user_id)
    return [
        await _summary(r, user_id=user.user_id, workflows=workflows) for r in rows
    ]


@router.get("/standing-tasks/{task_id}", response_model=StandingTaskSummary)
async def get_standing_task(
    task_id: str,
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
    workflows: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    row = await repo.get_by_id(task_id, user_id=user.user_id)
    if row is None:
        raise NotFoundError("站立任务不存在")
    return await _summary(row, user_id=user.user_id, workflows=workflows)


@router.patch("/standing-tasks/{task_id}", response_model=StandingTaskSummary)
async def update_standing_task(
    task_id: str,
    body: UpdateStandingTaskRequest,
    user: AuthUser,
    repo: StandingTaskRepository = Depends(get_standing_task_repo),
    folders: FolderRepository = Depends(get_folder_repo),
    workflows: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    existing = await repo.get_by_id(task_id, user_id=user.user_id)
    if existing is None:
        raise NotFoundError("站立任务不存在")

    fields = body.model_fields_set
    kwargs: dict = {}
    is_template = bool(getattr(existing, "template_key", None))

    if "name" in fields and not is_template:
        kwargs["name"] = body.name
    if "goal" in fields and not is_template:
        kwargs["goal"] = body.goal if body.goal is not None else ""
    if "folder_id" in fields and body.folder_id is not None:
        folder = await folders.get_by_id(body.folder_id, user_id=user.user_id)
        _require_cloud_folder(folder)
        kwargs["folder_id"] = body.folder_id
    if "enabled" in fields:
        kwargs["enabled"] = body.enabled
    if "permission_axes" in fields and body.permission_axes is not None:
        kwargs["permission_axes"] = body.permission_axes.to_axes().to_dict()
    if "clear_workflow" in fields and body.clear_workflow:
        kwargs["workflow_id"] = None
    elif "workflow_id" in fields and body.workflow_id is not None:
        await _require_owned_workflow(
            workflows, user_id=user.user_id, workflow_id=body.workflow_id
        )
        kwargs["workflow_id"] = body.workflow_id
    if "template_config" in fields:
        if not is_template:
            raise ValidationError("仅系统模板任务可设置 template_config")
        cfg = normalize_template_config(
            body.template_config.model_dump() if body.template_config else None
        )
        await _validate_template_folder_ids(
            folders, user_id=user.user_id, folder_ids=list(cfg["folder_ids"])
        )
        kwargs["template_config"] = cfg
        if existing.template_key == DAILY_CONVERSATION_REVIEW:
            kwargs["goal"] = daily_review_goal()

    plaintext_secret: str | None = None
    target_kind = body.trigger_kind if "trigger_kind" in fields else existing.trigger_kind

    if is_template and "trigger_kind" in fields and body.trigger_kind == "webhook":
        raise ValidationError("系统模板任务不可改为 webhook")

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
    return await _summary(
        row,
        user_id=user.user_id,
        workflows=workflows,
        webhook_secret=plaintext_secret,
    )


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
        items=[
            StandingTaskRunSummary.model_validate(r).model_copy(
                update={"task_name": task_name}
            )
            for r, task_name in items
        ],
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
