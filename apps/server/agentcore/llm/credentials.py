"""Per-turn LLM credential carrier and cloud-proxy HTTP headers.

Attribution headers let the inference proxy stamp each proxied LLM call with
the sidecar worker's run tree (run / agent / role / persona) so per-call detail
rows and per-run aggregates stay isomorphic with in-process cloud turns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agentcore.llm.profiles import PLATFORM_MODEL_FLASH

INFERENCE_CONVERSATION_HEADER = "X-AgentCore-Conversation"
INFERENCE_TRACE_HEADER = "X-AgentCore-Trace"
INFERENCE_MESSAGE_HEADER = "X-AgentCore-Message"
INFERENCE_RUN_HEADER = "X-AgentCore-Run"
INFERENCE_PARENT_RUN_HEADER = "X-AgentCore-Parent-Run"
INFERENCE_AGENT_HEADER = "X-AgentCore-Agent"
INFERENCE_ROLE_HEADER = "X-AgentCore-Role"
INFERENCE_PERSONA_HEADER = "X-AgentCore-Persona"
INFERENCE_CALL_HEADER = "X-AgentCore-Call"

CredentialOrigin = Literal["user", "platform"]


@dataclass(frozen=True)
class LLMCredentials:
    api_key: str
    base_url: str
    default_model: str = field(default=PLATFORM_MODEL_FLASH)
    extra_headers: dict[str, str] | None = None
    # Call-level origin for pricing: user BYOK → estimated ledger; platform → billed.
    source: CredentialOrigin = "user"
    # Optional cheaper model for background purposes (legacy carrier; multi-provider
    # resolves the background model via the account-level pointer, not this field).
    background_model: str | None = None
    # The BYOK provider these credentials came from (user_llm_providers.id), when a
    # specific 服务商 was resolved. None for the platform key / unspecified.
    provider_id: str | None = None


def bind_credential_pricing_context(creds: LLMCredentials | None) -> None:
    """Bind call-level ``credential_source`` (+ optional ``provider_id``) into structlog.

    Fresh turns (:func:`prepare_chat_turn`) and durable resumes must both call this
    before any LLM work — ``calculate_cost`` / ``log_llm_call`` / the call meter read
    ambient ``credential_source`` when the call site does not pass an explicit source.
    Skipping the bind on resume made BYOK calls fall through to ``platform`` and
    write false billed amounts.

    When ``creds.provider_id`` is set it is bound as ambient ``provider_id`` so
    failure / stall / turn-complete lines can attach it without logging secrets or
    ``base_url``. Platform / unset → leave ``provider_id`` unbound (callers skip).
    """
    from agentcore.core.log_context import bind_log_context

    if creds is None:
        bind_log_context(credential_source="platform")
        return
    bind_log_context(credential_source=creds.source)
    if creds.provider_id:
        bind_log_context(provider_id=creds.provider_id)

