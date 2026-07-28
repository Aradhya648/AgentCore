"""W3 conversation-scoped external directory grants (readonly | organize).

Separate from workspace binding — grants add ``external/<alias>/`` mounts for
file tools within one conversation; they never replace the bound workspace root.
Persisted in Postgres for the conversation lifetime (not the API process).
"""

from fastapi import APIRouter, Depends, Query

from agentcore.api.dependencies import AuthUser, get_conversation_repo
from agentcore.api.schemas import (
    ExternalGrantItem,
    ExternalGrantListResponse,
    ExternalGrantResponse,
    GrantExternalReadonlyRequest,
    StatusResponse,
)
from agentcore.core.errors import NotFoundError
from agentcore.db.repositories import ConversationRepository
from agentcore.workspace import grant_store
from agentcore.workspace.external_mounts import external_ns

from ._helpers import _get_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _item(m) -> ExternalGrantItem:
    return ExternalGrantItem(
        alias=m.alias,
        root_id=m.root_id,
        label=m.label,
        namespace=external_ns(m.alias),
        mode=m.mode,
    )


@router.get(
    "/{conversation_id}/workspace/external-grants",
    response_model=ExternalGrantListResponse,
)
async def list_external_grants(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    return ExternalGrantListResponse(
        data=[_item(m) for m in await grant_store.list_grants(conversation_id)]
    )


@router.post(
    "/{conversation_id}/workspace/external-grants",
    response_model=ExternalGrantResponse,
    status_code=201,
)
async def grant_external_folder(
    conversation_id: str,
    body: GrantExternalReadonlyRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Register a conversation mount after the user confirms via folder picker."""
    await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    mount = await grant_store.add_grant(
        conversation_id,
        root_id=body.root_id,
        label=body.label,
        alias_hint=body.alias_hint,
        mode=body.mode,
    )
    return ExternalGrantResponse(grant=_item(mount))


@router.delete(
    "/{conversation_id}/workspace/external-grants",
    response_model=StatusResponse,
)
async def revoke_external_grants(
    conversation_id: str,
    user: AuthUser,
    alias: str | None = Query(None),
    root_id: str | None = Query(None),
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Revoke one grant (by alias or root_id) or all grants for the conversation."""
    await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    if alias is None and root_id is None:
        await grant_store.clear_conversation(conversation_id)
        return StatusResponse()
    ok = await grant_store.revoke_grant(conversation_id, alias=alias, root_id=root_id)
    if not ok:
        raise NotFoundError("授权不存在或已撤销")
    return StatusResponse()
