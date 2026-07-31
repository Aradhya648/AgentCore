"""User workflow CRUD + run-once (direct-start bypass) + official playbook copy."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import (
    AuthUser,
    get_folder_repo,
    get_user_workflow_repo,
)
from agentcore.api.schemas import StatusResponse
from agentcore.api.schemas.workflows import (
    CreateWorkflowRequest,
    FromPlaybookRequest,
    PlaybookTemplateSummary,
    RunWorkflowRequest,
    RunWorkflowResponse,
    UpdateWorkflowRequest,
    WorkflowSummary,
)
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.db.repositories import FolderRepository, UserWorkflowRepository
from agentcore.workflows.playbook_templates import (
    PlaybookTemplateError,
    instantiate_from_playbook,
    list_playbook_templates,
)
from agentcore.workflows.runner import dispatch_workflow_run

router = APIRouter(tags=["workflows"])


def _require_folder(folder) -> None:
    if folder is None:
        raise NotFoundError("工作区不存在")


@router.get("/workflows", response_model=list[WorkflowSummary])
async def list_workflows(
    user: AuthUser,
    repo: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    rows = await repo.list_by_user(user.user_id)
    return [WorkflowSummary.from_row(r) for r in rows]


@router.get(
    "/workflow-playbook-templates",
    response_model=list[PlaybookTemplateSummary],
)
async def list_workflow_playbook_templates(user: AuthUser):
    """Official playbooks as read-only workflow templates (使用 = 复制为我的)."""
    _ = user
    return [
        PlaybookTemplateSummary(
            id=item.id,
            title=item.title,
            summary=item.summary,
            primary_slots=item.primary_slots,
        )
        for item in list_playbook_templates()
    ]


@router.post("/workflows", response_model=WorkflowSummary, status_code=201)
async def create_workflow(
    body: CreateWorkflowRequest,
    user: AuthUser,
    repo: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    row = await repo.create(
        user_id=user.user_id,
        name=body.name,
        description=body.description,
        definition=body.definition.model_dump(),
    )
    return WorkflowSummary.from_row(row)


@router.post(
    "/workflows/from-playbook",
    response_model=WorkflowSummary,
    status_code=201,
)
async def create_workflow_from_playbook(
    body: FromPlaybookRequest,
    user: AuthUser,
    repo: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    """Expand an official playbook once and save as a user workflow (not into PLAYBOOKS)."""
    try:
        name, description, definition = instantiate_from_playbook(
            body.playbook,
            body.slots,
            name=body.name,
        )
    except PlaybookTemplateError as e:
        raise ValidationError(str(e)) from e
    row = await repo.create(
        user_id=user.user_id,
        name=name,
        description=description,
        definition=definition,
    )
    return WorkflowSummary.from_row(row)


@router.get("/workflows/{workflow_id}", response_model=WorkflowSummary)
async def get_workflow(
    workflow_id: str,
    user: AuthUser,
    repo: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    row = await repo.get_by_id(workflow_id, user_id=user.user_id)
    if row is None:
        raise NotFoundError("工作流不存在")
    return WorkflowSummary.from_row(row)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowSummary)
async def update_workflow(
    workflow_id: str,
    body: UpdateWorkflowRequest,
    user: AuthUser,
    repo: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    desc_arg: object = ...
    if body.clear_description or body.description is not None:
        desc_arg = None if body.clear_description else body.description
    row = await repo.update(
        workflow_id,
        user_id=user.user_id,
        name=body.name,
        description=desc_arg,
        definition=body.definition.model_dump() if body.definition is not None else None,
    )
    if row is None:
        raise NotFoundError("工作流不存在")
    return WorkflowSummary.from_row(row)


@router.delete("/workflows/{workflow_id}", response_model=StatusResponse)
async def delete_workflow(
    workflow_id: str,
    user: AuthUser,
    repo: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    ok = await repo.delete(workflow_id, user_id=user.user_id)
    if not ok:
        raise NotFoundError("工作流不存在")
    return StatusResponse()


@router.post("/workflows/{workflow_id}/run", response_model=RunWorkflowResponse)
async def run_workflow(
    workflow_id: str,
    body: RunWorkflowRequest,
    user: AuthUser,
    folders: FolderRepository = Depends(get_folder_repo),
    repo: UserWorkflowRepository = Depends(get_user_workflow_repo),
):
    row = await repo.get_by_id(workflow_id, user_id=user.user_id)
    if row is None:
        raise NotFoundError("工作流不存在")
    folder = await folders.get_by_id(body.folder_id, user_id=user.user_id)
    _require_folder(folder)
    try:
        conversation_id = await dispatch_workflow_run(
            user_id=user.user_id,
            workflow_id=row.id,
            workflow_version=int(row.version or 1),
            definition=dict(row.definition or {}),
            folder_id=body.folder_id,
            note=body.note,
            conversation_id=body.conversation_id,
            workflow_name=row.name,
        )
    except LookupError as e:
        raise NotFoundError(str(e) or "资源不存在") from e
    except ValueError as e:
        raise ValidationError(str(e)) from e
    return RunWorkflowResponse(
        conversation_id=conversation_id,
        workflow_id=row.id,
        workflow_version=int(row.version or 1),
    )
