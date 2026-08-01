"""Shared mappers: a ledger aggregate dict → the cost/usage API schema.

Single source for turning a ``cost_events`` rollup (the repository's dict shape)
into the wire schema, shared by the per-user 用量 endpoints (``usage.py``) and the
admin 全站看板 (``admin.py``). The ledger is already priced (用量/成本不变量 #2:
``calculate_cost`` ran at write time), so this only *reads* the stored components
— it never re-prices. ``cny_total`` is yuan (``nano / 1e9``); no FX.
"""

from agentcore.api.schemas import CostBreakdown, UsageBreakdown
from agentcore.llm.pricing import nano_to_yuan


def cost_breakdown(cost: dict) -> CostBreakdown:
    """Map a ledger cost dict (integer nano-CNY components) to the API schema,
    attaching display yuan via ``nano_to_yuan``."""
    total = int(cost.get("total", 0))
    return CostBreakdown(
        input=int(cost.get("input", 0)),
        cached=int(cost.get("cached", 0)),
        output=int(cost.get("output", 0)),
        total=total,
        currency=str(cost.get("currency", "CNY")),
        cny_total=nano_to_yuan(total),
        pricing_source=str(cost.get("pricing_source") or "curated"),
    )


def estimated_cost_breakdown(
    *,
    estimated_nano: int = 0,
    cost: dict | None = None,
) -> CostBreakdown | None:
    """BYOK estimate breakdown, or ``None`` when there is nothing to show."""
    body = cost or {}
    total = int(estimated_nano or body.get("total", 0) or 0)
    if total <= 0 and not any(int(body.get(k, 0) or 0) for k in ("input", "cached", "output")):
        return None
    return CostBreakdown(
        input=int(body.get("input", 0)),
        cached=int(body.get("cached", 0)),
        output=int(body.get("output", 0)),
        total=total,
        currency=str(body.get("currency", "CNY")),
        cny_total=nano_to_yuan(total),
        pricing_source=str(body.get("pricing_source") or "estimated"),
    )


def usage_breakdown(tokens: dict) -> UsageBreakdown:
    """Map a ledger token dict to the API schema (absent keys → 0)."""
    return UsageBreakdown(
        input=int(tokens.get("input", 0)),
        output=int(tokens.get("output", 0)),
        reasoning=int(tokens.get("reasoning", 0)),
        cache_hit=int(tokens.get("cache_hit", 0)),
        cache_miss=int(tokens.get("cache_miss", 0)),
    )
