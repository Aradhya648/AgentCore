"""Agent collaboration audit API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AgentAuditEventLine(BaseModel):
    id: str
    turn_id: str
    trace_id: str | None
    execution_id: str | None
    run_id: str | None
    parent_run_id: str | None
    seq: int
    category: str
    action: str
    actor_kind: str
    target_type: str | None
    target_ref: str | None
    outcome: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class AgentAuditListResponse(BaseModel):
    data: list[AgentAuditEventLine]
    total: int
    causal_graph: "AuditCausalGraph | None" = None


class AuditCausalNode(BaseModel):
    run_id: str
    role: str | None = None
    parent_run_id: str | None = None


class AuditCausalEdge(BaseModel):
    kind: str
    from_run_id: str = Field(alias="from")
    to_run_id: str = Field(alias="to")

    model_config = {"populate_by_name": True}


class AuditCausalGraph(BaseModel):
    nodes: list[AuditCausalNode]
    edges: list[AuditCausalEdge]


class AdminAgentAuditSummary(BaseModel):
    """Platform-wide agent audit aggregates for the admin dashboard widget."""

    events: int
    failures: int
    approval_timeouts: int
    approval_denied: int
    delegate_plans: int
    audit_drops: int
