"""Ambient debate steer — fire-and-forget mid-flight boss intervention (逐轮掌舵)."""

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import AuthUser, get_conversation_repo
from agentcore.api.schemas import SubmitDebateSteerRequest, SubmitDebateSteerResponse
from agentcore.core.logging import get_logger
from agentcore.db.repositories import ConversationRepository
from agentcore.runtime.debate.steer_queue import enqueue_steer, peek_steer_count

from ._helpers import _require_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])

logger = get_logger(__name__)


@router.post("/{conversation_id}/debate-steer", response_model=SubmitDebateSteerResponse)
async def submit_debate_steer(
    conversation_id: str,
    body: SubmitDebateSteerRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Queue an ambient steer for the live debate (下一轮边界非阻塞生效).

    The Moderator never hard-stops for the user — this fire-and-forget channel is the
    boss直控 path (同 ``run-redirect`` 模式). Applied at the next round boundary via
    existing ``pending_interjections`` / ``focus_override`` / ``CONCLUDE`` mechanisms.
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    enqueue_steer(
        execution_id=body.execution_id,
        conversation_id=conversation_id,
        decision=body.decision,
        focus=body.focus,
        ask=body.ask,
        ask_target=body.ask_target,
    )
    queued = peek_steer_count(body.execution_id)
    logger.info(
        "debate_steer.queued",
        conversation_id=conversation_id,
        execution_id=body.execution_id,
        decision=body.decision,
        queued=queued,
    )
    return SubmitDebateSteerResponse(queued=queued)
