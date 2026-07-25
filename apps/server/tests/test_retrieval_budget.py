"""检索预算 A1: structured defaults, explicit override, tool_exec charge / exhaust."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentcore.core.types import ToolCategory
from agentcore.llm.provider.protocol import ToolCall, ToolCallFunction
from agentcore.runtime.engine.tool_exec import execute_tools
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.retrieval_budget import (
    BUDGET_EXHAUSTED_FEEDBACK,
    DEFAULT_RETRIEVAL_BUDGET,
    DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER,
    RETRIEVAL_BUDGET_CRITICAL_REMAINING,
    RETRIEVAL_TOOL_NAMES,
    charges_retrieval_budget,
    default_retrieval_budget,
    format_retrieval_budget_critical_prompt,
    format_retrieval_budget_line,
    is_retrieval_budget_critical,
    rework_refill_slots,
)
from agentcore.runtime.runs.types import Deliverable, RunSpec
from agentcore.tools.protocol import RetrievalBudgetState, ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _spec(
    *,
    deps: list[str] | None = None,
    form: str | None = None,
    budget: int | None = None,
    tools: list[str] | None = None,
) -> RunSpec:
    deliverable = Deliverable(form=form) if form else None  # type: ignore[arg-type]
    return RunSpec(
        run_id="n1",
        task="t",
        role="r",
        depends_on=deps or [],
        deliverable=deliverable,
        retrieval_budget=budget,
        tools=tools,
    )


def test_structured_default_unified_non_prose():
    """任意非 prose → 统一默认 14（root / light / files / 下游同额）。"""
    assert DEFAULT_RETRIEVAL_BUDGET == 14
    assert default_retrieval_budget(_spec()) == DEFAULT_RETRIEVAL_BUDGET
    assert (
        default_retrieval_budget(_spec(), complexity_hint="light")
        == DEFAULT_RETRIEVAL_BUDGET
    )
    assert default_retrieval_budget(_spec(form="files")) == DEFAULT_RETRIEVAL_BUDGET
    assert (
        default_retrieval_budget(_spec(deps=["u"], form="files"))
        == DEFAULT_RETRIEVAL_BUDGET
    )
    assert default_retrieval_budget(_spec(deps=["u"])) == DEFAULT_RETRIEVAL_BUDGET


def test_structured_default_prose_is_zero():
    """form=prose → 0（硬例外；含无上游 root 与下游合成波）。"""
    assert default_retrieval_budget(_spec(form="prose")) == 0
    assert default_retrieval_budget(_spec(deps=["up"], form="prose")) == 0


def test_debate_dossier_narrow_exception_constant():
    """有案卷辩手残搜 2：窄硬例外，不是结构猜档。"""
    assert DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER == 2
    assert DEFAULT_RETRIEVAL_BUDGET_DEBATER_WITH_DOSSIER < DEFAULT_RETRIEVAL_BUDGET


def test_retrieval_budget_critical_helpers():
    """临界剩余 ≤2 且未耗尽 → 注入 reflection；耗尽 / 关闭不走此路径。"""
    assert RETRIEVAL_BUDGET_CRITICAL_REMAINING == 2
    assert is_retrieval_budget_critical(2, limit=14) is True
    assert is_retrieval_budget_critical(1, limit=14) is True
    assert is_retrieval_budget_critical(3, limit=14) is False
    assert is_retrieval_budget_critical(0, limit=14) is False
    assert is_retrieval_budget_critical(1, limit=0) is False
    prompt = format_retrieval_budget_critical_prompt(remaining=2, limit=14)
    assert prompt.startswith("[系统提示]")
    assert "仅剩 2" in prompt
    assert "14" in prompt
    assert "扇出" in prompt


def test_build_plan_applies_defaults_and_strips_search_for_prose_downstream():
    valid = {"web_search", "read_url", "file_read", "handoff", "escalate"}
    plan, errors = build_run_plan(
        [
            {"id": "r1", "role": "研究员", "task": "调研竞品"},
            {
                "id": "w1",
                "role": "写手",
                "task": "综合成文",
                "depends_on": ["r1"],
                "deliverable": {"form": "prose"},
            },
        ],
        valid_tools=valid,
    )
    assert errors == []
    by_role = {n.role: n for n in plan.nodes}
    assert by_role["研究员"].retrieval_budget == DEFAULT_RETRIEVAL_BUDGET
    assert by_role["写手"].retrieval_budget == 0
    writer_tools = by_role["写手"].tools
    assert writer_tools is not None
    assert "web_search" not in writer_tools
    assert "read_url" not in writer_tools
    assert "file_read" in writer_tools


def test_build_plan_explicit_zero_on_root_strips_tools_and_stays_zero():
    """CEO 在无上游 root 显式 retrieval_budget=0 → 保持 0 且剥离检索工具。"""
    plan, errors = build_run_plan(
        [{"role": "研究员", "task": "只用现有材料成文", "retrieval_budget": 0}],
        valid_tools={"web_search", "read_url", "file_read"},
    )
    assert errors == []
    node = plan.nodes[0]
    assert node.retrieval_budget == 0
    assert node.tools is not None
    assert "web_search" not in node.tools
    assert "read_url" not in node.tools


def test_ceo_explicit_budget_overrides_default():
    plan, errors = build_run_plan(
        [
            {"id": "r", "role": "研究员", "task": "深挖", "retrieval_budget": 20},
            {
                "id": "w",
                "role": "写手",
                "task": "写",
                "depends_on": ["r"],
                "deliverable": {"form": "prose"},
                "retrieval_budget": 2,
            },
        ],
        valid_tools={"web_search", "read_url", "file_read"},
    )
    assert errors == []
    by_role = {n.role: n for n in plan.nodes}
    assert by_role["研究员"].retrieval_budget == 20
    assert by_role["写手"].retrieval_budget == 2
    # explicit non-zero ⇒ do not strip retrieval tools (unrestricted stays None)
    assert by_role["写手"].tools is None


def test_charges_skips_cache_and_failures():
    ok_live = ToolResult(tool_call_id="", success=True, output="x", metadata={})
    ok_cached = ToolResult(
        tool_call_id="", success=True, output="x", metadata={"cached": True}
    )
    failed = ToolResult(tool_call_id="", success=False, output="", error="A3 reject")
    assert charges_retrieval_budget(ok_live) is True
    assert charges_retrieval_budget(ok_cached) is False
    assert charges_retrieval_budget(failed) is False


def test_budget_line_mentions_continue_from():
    line = format_retrieval_budget_line(5)
    assert "5" in line
    assert "continue_from_run_id" in line
    zero = format_retrieval_budget_line(0)
    assert "0" in zero
    assert "不装配" in zero


def _ctx(*, budget: RetrievalBudgetState | None) -> ToolContext:
    return ToolContext(
        execution_id="e",
        run_id="r1",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        retrieval_budget=budget,
    )


def _call(tool_id: str, name: str = "web_search") -> ToolCall:
    return ToolCall(
        id=tool_id,
        function=ToolCallFunction(name=name, arguments='{"query":"q"}'),
    )


class _SearchStub:
    def __init__(self, *, cached: bool = False, fail: bool = False) -> None:
        self.calls = 0
        self._cached = cached
        self._fail = fail

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description="stub",
            parameters={"type": "object", "properties": {}},
            category=ToolCategory.SEARCH,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls += 1
        if self._fail:
            return ToolResult(tool_call_id="", success=False, error="bad query")
        meta = {"cached": True} if self._cached else {}
        return ToolResult(tool_call_id="", success=True, output="hits", metadata=meta)


@pytest.mark.asyncio
async def test_tool_exec_exhausts_and_returns_structured_feedback():
    stub = _SearchStub()
    reg = ToolRegistry()
    reg.register(stub)
    state = RetrievalBudgetState(limit=1)
    sink = EventSink()

    msgs1, _, _ = await execute_tools(
        [_call("c1")], reg, _ctx(budget=state), sink, run_id="r1"
    )
    assert stub.calls == 1
    assert state.used == 1
    assert "hits" in (msgs1[0].content or "")

    msgs2, _, _ = await execute_tools(
        [_call("c2")], reg, _ctx(budget=state), sink, run_id="r1"
    )
    assert stub.calls == 1  # second call blocked
    assert BUDGET_EXHAUSTED_FEEDBACK in (msgs2[0].content or "")
    assert "continue_from_run_id" in (msgs2[0].content or "")
    assert state.used == 1


@pytest.mark.asyncio
async def test_tool_exec_cache_hit_does_not_consume_budget():
    stub = _SearchStub(cached=True)
    reg = ToolRegistry()
    reg.register(stub)
    state = RetrievalBudgetState(limit=1)
    sink = EventSink()

    await execute_tools([_call("c1")], reg, _ctx(budget=state), sink, run_id="r1")
    assert stub.calls == 1
    assert state.used == 0

    # still have budget for a live call
    stub2 = _SearchStub(cached=False)
    reg2 = ToolRegistry()
    reg2.register(stub2)
    await execute_tools([_call("c2")], reg2, _ctx(budget=state), sink, run_id="r1")
    assert stub2.calls == 1
    assert state.used == 1


@pytest.mark.asyncio
async def test_tool_exec_failed_call_does_not_consume_budget():
    stub = _SearchStub(fail=True)
    reg = ToolRegistry()
    reg.register(stub)
    state = RetrievalBudgetState(limit=1)
    sink = EventSink()

    await execute_tools([_call("c1")], reg, _ctx(budget=state), sink, run_id="r1")
    assert stub.calls == 1
    assert state.used == 0


def test_retrieval_tool_names_cover_search_and_read():
    assert frozenset({"web_search", "read_url"}) == RETRIEVAL_TOOL_NAMES


def test_rework_refill_slots_zero_after_wind_down():
    assert rework_refill_slots(original_limit=8, wind_down_entered=True) == 0
    assert rework_refill_slots(original_limit=0, wind_down_entered=False) == 0
    assert rework_refill_slots(original_limit=8, wind_down_entered=False) == 4
    assert rework_refill_slots(original_limit=1, wind_down_entered=False) == 1


@pytest.mark.asyncio
async def test_refill_within_cap_does_not_raise_past_original():
    rb = RetrievalBudgetState(limit=4)
    assert await rb.try_reserve()
    assert await rb.try_reserve()
    assert await rb.try_reserve()
    assert await rb.try_reserve()
    assert rb.remaining == 0
    # Exhausted within original — within_cap cannot grow past cap=4.
    remaining = await rb.refill_within_cap(2, cap=4)
    assert remaining == 0
    assert rb.limit == 4
    # Headroom below cap still works (simulate partial spend after a lower limit).
    rb2 = RetrievalBudgetState(limit=2)
    await rb2.try_reserve()
    await rb2.try_reserve()
    rem2 = await rb2.refill_within_cap(3, cap=5)
    assert rb2.limit == 5
    assert rem2 == 3
