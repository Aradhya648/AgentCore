"""In-process cloud LLM call metering → shared :mod:`cost_ledger_queue`.

Only active when the ledger drain is running (API server lifespan). Sidecar
never starts the drain; its spend is recorded exclusively by the cloud
inference proxy. Call details are authoritative; per-run aggregates are
upserted from those details (``materialize_runs=True``, isomorphic with the
proxy path). Turn finalize still reconciles orphans (e.g. vision) and re-reads
the product view for ``cost.recorded`` / ``messages.cost``.
"""

from __future__ import annotations

from dataclasses import asdict

from agentcore.core.log_context import get_log_value
from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.runtime.costing import ROLE_CAPTAIN, ROLE_MEMBER, priced_call_cost

logger = get_logger(__name__)

_BACKGROUND_ROLES = frozenset({"title", "memory"})

# Proxy-forwarded unary calls still emit ``llm.call`` (latency obs) via
# provider.complete → log_llm_call, but billing must be ``proxy_spend`` only —
# otherwise one physical upstream call lands two ``cost_calls`` rows.
PROXY_LLM_SCENARIO = "inference.proxy"

# board_read vision: ``log_llm_call`` is observability-only; ``BoardReadTool``
# prices a separate ``role=vision`` ``cost_runs`` row (different model tier).
# Metering here would mis-attribute tokens onto the parent run_id and double-bill
# when finalize also records the vision orphan.
_VISION_SCENARIO_PREFIX = "vision."


def maybe_enqueue_inprocess_call(
    *,
    model: str,
    usage: TokenUsage,
    duration_ms: int = 0,
    scenario: str | None = None,
    credential_source: str | None = None,
) -> str | None:
    """Enqueue one ``cost_calls`` row (+ materialize its run) when drain is live.

    Skips when: drain not running (sidecar / unit tests), missing user or
    conversation context, zero usage, ``scenario`` is the inference proxy
    marker (proxy already records via ``proxy_spend``), or a vision board_read
    (billed only via the turn ``cost_runs`` vision row).
    """
    if scenario == PROXY_LLM_SCENARIO:
        return None
    if scenario and scenario.startswith(_VISION_SCENARIO_PREFIX):
        return None

    from agentcore.billing.cost_ledger_queue import get_cost_ledger_queue
    from agentcore.llm.pricing import CredentialSource, resolve_credential_source

    queue = get_cost_ledger_queue()
    if not queue.running:
        return None

    user_id = get_log_value("user_id")
    conversation_id = get_log_value("conversation_id")
    if not user_id or not conversation_id:
        return None

    run_id = get_log_value("run_id") or None
    agent_id = get_log_value("agent_id") or None
    parent_run_id = get_log_value("parent_run_id") or None
    persona = get_log_value("persona") or None
    cost_role = get_log_value("cost_role") or None
    message_id = get_log_value("message_id") or None
    trace_id = get_log_value("trace_id") or None

    if cost_role in _BACKGROUND_ROLES or cost_role in ("captain", "member", "arena", "vision"):
        role = cost_role
    elif agent_id in ("CEO", "captain"):
        role = ROLE_CAPTAIN
    elif run_id:
        role = ROLE_MEMBER
    else:
        # Off-turn title/memory often lack run stamps; leave role as captain-shaped
        # only when nothing else is known — callers that know better bind cost_role.
        role = ROLE_CAPTAIN

    explicit: CredentialSource | None = (
        credential_source if credential_source in ("user", "platform", "vendor") else None
    )
    source = resolve_credential_source(credential_source=explicit, model=model)
    call = priced_call_cost(
        model=model,
        usage=usage,
        role=role,
        run_id=run_id,
        parent_run_id=parent_run_id,
        agent_id=agent_id,
        persona=persona,
        duration_ms=duration_ms,
        credential_source=source,
    )
    record_id = queue.enqueue_calls(
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        trace_id=trace_id,
        calls=[asdict(call)],
        source="inprocess_call",
        materialize_runs=True,
    )
    if record_id is None:
        logger.warning(
            "cost.inprocess_call_enqueue_failed",
            conversation_id=conversation_id,
            run_id=call.run_id,
        )
    return record_id
