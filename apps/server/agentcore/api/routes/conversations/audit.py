"""Owner-scoped agent audit timeline for one assistant turn."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from agentcore.api.dependencies import AuthUser, get_agent_audit_repo, get_conversation_repo
from agentcore.api.schemas.agent_audit import (
    AgentAuditEventLine,
    AgentAuditListResponse,
    AuditCausalEdge,
    AuditCausalGraph,
    AuditCausalNode,
)
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import AgentAuditEventRepository, ConversationRepository
from agentcore.runtime.audit.causal import build_causal_graph

from ._helpers import _require_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _to_causal_graph(raw: dict) -> AuditCausalGraph:
    return AuditCausalGraph(
        nodes=[AuditCausalNode.model_validate(n) for n in raw.get("nodes", [])],
        edges=[AuditCausalEdge.model_validate(e) for e in raw.get("edges", [])],
    )


@router.get(
    "/{conversation_id}/audit",
    response_model=AgentAuditListResponse,
)
async def list_conversation_audit(
    conversation_id: str,
    user: AuthUser,
    limit: int = Query(default=200, ge=1, le=500),
    category: str | None = Query(default=None, description="Optional category filter"),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    audit_repo: AgentAuditEventRepository = Depends(get_agent_audit_repo),
) -> AgentAuditListResponse:
    """Conversation-scoped security ledger (owner-scoped); includes preset changes."""
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    rows = await audit_repo.list_for_conversation(
        conversation_id=conversation_id,
        limit=limit,
        category=category,
    )
    if not rows:
        raise NotFoundError("该对话暂无审计记录")
    return AgentAuditListResponse(
        data=[AgentAuditEventLine.model_validate(row) for row in rows],
        total=len(rows),
    )


@router.get(
    "/{conversation_id}/messages/{message_id}/audit",
    response_model=AgentAuditListResponse,
)
async def list_turn_audit(
    conversation_id: str,
    message_id: str,
    user: AuthUser,
    include_causal: bool = Query(default=False, description="Include runtime causal graph"),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    audit_repo: AgentAuditEventRepository = Depends(get_agent_audit_repo),
) -> AgentAuditListResponse:
    """Turn audit timeline for one assistant message (owner-scoped)."""
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    rows = await audit_repo.list_for_turn(conversation_id=conversation_id, turn_id=message_id)
    if not rows:
        raise NotFoundError("该回合暂无审计记录")
    causal = _to_causal_graph(build_causal_graph(rows)) if include_causal else None
    return AgentAuditListResponse(
        data=[AgentAuditEventLine.model_validate(row) for row in rows],
        total=len(rows),
        causal_graph=causal,
    )


@router.get(
    "/{conversation_id}/audit/file",
    response_model=AgentAuditListResponse,
)
async def list_file_audit(
    conversation_id: str,
    user: AuthUser,
    path: str = Query(..., min_length=1, description="Workspace-relative file path"),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    audit_repo: AgentAuditEventRepository = Depends(get_agent_audit_repo),
) -> AgentAuditListResponse:
    """File-attribution audit timeline for one workspace path (owner-scoped)."""
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    rows = await audit_repo.list_for_file(conversation_id=conversation_id, path=path)
    if not rows:
        raise NotFoundError("该路径暂无审计记录")
    return AgentAuditListResponse(
        data=[AgentAuditEventLine.model_validate(row) for row in rows],
        total=len(rows),
    )
