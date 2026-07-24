"""Inference ``proxy_spend`` enqueue — thin facade over :mod:`cost_ledger_queue`.

Prices one proxied LLM call into a ``CallCost`` detail row (with optional run /
persona attribution from sidecar headers), then enqueues onto the shared ledger
outbox. Drain inserts ``cost_calls`` and materializes ``cost_events`` by run_id
(as-built: 成本配额 §三). Drain / lifespan live on ``CostLedgerQueue``.
"""

from __future__ import annotations

from dataclasses import asdict

from agentcore.billing.cost_ledger_queue import (
    CostLedgerQueue,
    get_cost_ledger_queue,
    reset_cost_ledger_queue_for_tests,
)
from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import TokenUsage
from agentcore.runtime.costing import ROLE_CAPTAIN, priced_call_cost

logger = get_logger(__name__)

# Re-export so existing imports (`get_proxy_spend_queue`, test reset) keep working.
__all__ = [
    "ProxySpendQueue",
    "get_proxy_spend_queue",
    "reset_proxy_spend_queue_for_tests",
]


class ProxySpendQueue:
    """Compatibility wrapper: proxy spend → shared :class:`CostLedgerQueue`."""

    def __init__(self, ledger: CostLedgerQueue | None = None) -> None:
        self._ledger = ledger or get_cost_ledger_queue()

    @property
    def running(self) -> bool:
        return self._ledger.running

    def enqueue(
        self,
        *,
        user_id: str,
        conversation_id: str,
        model: str,
        usage: TokenUsage,
        trace_id: str | None = None,
        message_id: str | None = None,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        agent_id: str | None = None,
        role: str | None = None,
        persona: str | None = None,
        call_id: str | None = None,
        credential_source: str | None = None,
    ) -> str | None:
        """Price one inference call and enqueue a detail row (+ materialize run)."""
        if not conversation_id:
            logger.warning(
                "inference.proxy_spend_no_conversation",
                user_id=user_id,
                model=model,
            )
            return None

        from agentcore.llm.pricing import CredentialSource, resolve_credential_source

        explicit: CredentialSource | None = (
            credential_source if credential_source in ("user", "platform", "vendor") else None
        )
        source = resolve_credential_source(credential_source=explicit, model=model)
        call = priced_call_cost(
            model=model or "",
            usage=usage,
            role=(role or "").strip() or ROLE_CAPTAIN,
            run_id=run_id,
            parent_run_id=parent_run_id,
            agent_id=agent_id,
            persona=persona,
            call_id=call_id,
            credential_source=source,
        )
        record_id = self._ledger.enqueue_calls(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            trace_id=trace_id,
            calls=[asdict(call)],
            source="proxy_spend",
            materialize_runs=True,
        )
        if record_id is None:
            logger.error(
                "inference.proxy_spend_enqueue_failed",
                user_id=user_id,
                conversation_id=conversation_id,
            )
        else:
            logger.info(
                "inference.proxy_spend_enqueued",
                record_id=record_id,
                call_id=call.call_id,
                run_id=call.run_id,
                role=call.role,
                persona=call.persona,
                conversation_id=conversation_id,
            )
        return record_id

    def start(self) -> None:
        self._ledger.start()

    async def stop(self) -> None:
        await self._ledger.stop()

    async def drain_once(self) -> int:
        return await self._ledger.drain_once()


def get_proxy_spend_queue() -> ProxySpendQueue:
    """Process-wide proxy facade over the shared ledger queue."""
    return ProxySpendQueue(get_cost_ledger_queue())


def reset_proxy_spend_queue_for_tests() -> ProxySpendQueue:
    """Replace the shared ledger singleton and return a proxy facade (tests only)."""
    return ProxySpendQueue(reset_cost_ledger_queue_for_tests())
