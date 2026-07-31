"""User workflow API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agentcore.workflows.definition import validate_workflow_definition


class WorkflowDefinitionModel(BaseModel):
    """Canvas JSON: nodes + edges (agent_step | human_gate)."""

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("nodes", "edges", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> object:
        if v is None:
            return []
        return v


class CreateWorkflowRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    definition: WorkflowDefinitionModel

    @field_validator("definition")
    @classmethod
    def _validate_definition(cls, v: WorkflowDefinitionModel) -> WorkflowDefinitionModel:
        errors = validate_workflow_definition(v.model_dump())
        if errors:
            raise ValueError("；".join(errors))
        return v


class UpdateWorkflowRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    definition: WorkflowDefinitionModel | None = None
    # Explicit clear: pass description="" → stored as NULL via route.
    clear_description: bool = False

    @field_validator("definition")
    @classmethod
    def _validate_definition(
        cls, v: WorkflowDefinitionModel | None
    ) -> WorkflowDefinitionModel | None:
        if v is None:
            return None
        errors = validate_workflow_definition(v.model_dump())
        if errors:
            raise ValueError("；".join(errors))
        return v


class WorkflowSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    definition: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_row(cls, row) -> "WorkflowSummary":
        return cls(
            id=row.id,
            name=row.name,
            description=row.description,
            definition=dict(row.definition or {}),
            version=int(row.version or 1),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class RunWorkflowRequest(BaseModel):
    folder_id: str
    # Optional per-run supplement (does not rewrite the saved definition).
    note: str | None = Field(None, max_length=16_000)
    conversation_id: str | None = None


class RunWorkflowResponse(BaseModel):
    conversation_id: str
    workflow_id: str
    workflow_version: int


class PlaybookTemplateSummary(BaseModel):
    """Official playbook listed as a read-only workflow template."""

    id: str
    title: str
    summary: str
    primary_slots: str


class FromPlaybookRequest(BaseModel):
    """Copy an official playbook into a user workflow (use = 复制为我的)."""

    playbook: str = Field(..., min_length=1, max_length=80)
    slots: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(None, min_length=1, max_length=200)
