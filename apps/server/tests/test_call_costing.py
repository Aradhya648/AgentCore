"""Unit tests for per-call builders + run materialization (runtime/costing.py)."""

from agentcore.llm.provider.protocol import TokenUsage
from agentcore.runtime.costing import (
    ROLE_CAPTAIN,
    ROLE_MEMBER,
    priced_call_cost,
    run_cost_from_calls,
)


def test_priced_call_cost_and_run_materialization():
    usage1 = TokenUsage(input_tokens=100, output_tokens=10, cache_miss_tokens=100)
    usage2 = TokenUsage(input_tokens=50, output_tokens=5, cache_miss_tokens=50)
    c1 = priced_call_cost(
        model="deepseek-v4-flash",
        usage=usage1,
        role=ROLE_MEMBER,
        run_id="run-x",
        agent_id="run-x",
        persona="调研员",
        call_id="call_1",
        duration_ms=12,
    )
    c2 = priced_call_cost(
        model="deepseek-v4-flash",
        usage=usage2,
        role=ROLE_MEMBER,
        run_id="run-x",
        agent_id="run-x",
        persona="调研员",
        call_id="call_2",
        duration_ms=8,
    )
    assert c1.call_id == "call_1"
    assert c1.persona == "调研员"
    assert c1.cost_total_nano > 0

    agg = run_cost_from_calls([c1, c2])
    assert agg is not None
    assert agg.run_id == "run-x"
    assert agg.role == ROLE_MEMBER
    assert agg.persona == "调研员"
    assert agg.rounds == 2
    assert agg.tokens["input"] == 150
    assert agg.tokens["output"] == 15
    assert agg.cost_total_nano == c1.cost_total_nano + c2.cost_total_nano
    assert agg.duration_ms == 20


def test_run_cost_from_calls_empty():
    assert run_cost_from_calls([]) is None


def test_priced_call_without_run_mints_ids():
    call = priced_call_cost(
        model="deepseek-v4-flash",
        usage=TokenUsage(input_tokens=1, output_tokens=1, cache_miss_tokens=1),
        role=ROLE_CAPTAIN,
    )
    assert call.call_id.startswith("call_")
    assert call.run_id  # minted
    assert call.persona is None
