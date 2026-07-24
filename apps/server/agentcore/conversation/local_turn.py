"""Sidecar local-turn write-back — ``CloudStore.finalize(mode="local")``."""

from agentcore.conversation.store import get_cloud_store
from agentcore.core.log_context import log_context
from agentcore.llm.resolve import LLMCredentials


async def record_local_turn(
    *,
    conversation_id: str,
    user_id: str,
    user_message: str,
    assistant_content: str,
    assistant_reasoning: str | None = None,
    citations: list[dict] | None = None,
    evidence_ledger: list[dict] | None = None,
    runs: dict | None = None,
    journal: list[dict] | None = None,
    user_message_id: str,
    message_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    rounds: int = 0,
    trace_id: str,
    finish_reason: str | None = None,
    llm_credentials: LLMCredentials | None = None,
) -> dict:
    """Persist a turn that ran on the user's machine via the sidecar.

    Routes through ``CloudStore.finalize(mode="local")`` so D7 merge rules apply
    (content monotonic, status gate, journal seq upsert, no early-return).
    Spend is NOT recorded here — metered at ``/v1/inference``.
    """
    with log_context(trace_id=trace_id, conversation_id=conversation_id, user_id=user_id):
        result = await get_cloud_store().finalize(
            mode="local",
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=user_message,
            assistant_content=assistant_content,
            assistant_reasoning=assistant_reasoning,
            citations=citations,
            evidence_ledger=evidence_ledger,
            runs=runs,
            journal=journal,
            user_message_id=user_message_id,
            message_id=message_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_hit_tokens=cache_hit_tokens,
            cache_miss_tokens=cache_miss_tokens,
            rounds=rounds,
            trace_id=trace_id,
            finish_reason=finish_reason,
            llm_credentials=llm_credentials,
        )
        assert result is not None
        return result
