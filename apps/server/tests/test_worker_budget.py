"""Worker token/timeout 统一 backstop：未显式声明时回填全局 ceiling + 600s。"""

from __future__ import annotations

from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.types import Deliverable, RunPolicy, RunSpec
from agentcore.runtime.runs.worker_budget import (
    DIRECTED_SEARCH_TOOL_NAMES,
    WORKER_TIMEOUT_BACKSTOP_S,
    apply_worker_budgets_to_specs,
    ensure_directed_search_tools,
    is_deep_deliverable,
    is_directed_search_role,
    is_research_root,
)


def test_apply_fills_unified_backstop():
    """未声明 token_ceiling / timeout_s → 统一回填。"""
    spec = RunSpec(run_id="x", task="t", role="r", policy=RunPolicy())
    apply_worker_budgets_to_specs([spec], default_token_ceiling=600_000)
    assert spec.token_ceiling == 600_000
    assert spec.policy.timeout_s == WORKER_TIMEOUT_BACKSTOP_S == 600


def test_apply_preserves_pre_set_token_ceiling_and_timeout():
    """已声明的 token_ceiling / timeout_s 不动。"""
    spec = RunSpec(
        run_id="x",
        task="t",
        role="r",
        deliverable=Deliverable(requires_files=True),
        token_ceiling=50_000,
        policy=RunPolicy(timeout_s=90),
    )
    apply_worker_budgets_to_specs([spec], default_token_ceiling=600_000)
    assert spec.token_ceiling == 50_000
    assert spec.policy.timeout_s == 90


def test_apply_fills_timeout_when_ceiling_preset():
    """仅 token_ceiling 预置时仍回填 timeout。"""
    spec = RunSpec(
        run_id="x",
        task="t",
        role="r",
        token_ceiling=50_000,
        policy=RunPolicy(),
    )
    apply_worker_budgets_to_specs([spec], default_token_ceiling=600_000)
    assert spec.token_ceiling == 50_000
    assert spec.policy.timeout_s == WORKER_TIMEOUT_BACKSTOP_S


def test_build_plan_applies_unified_backstop_regardless_of_shape():
    """有上游 / 无上游 / 落盘 / 审校 — token/超时均走统一 backstop。"""
    plan, errors = build_run_plan(
        [
            {"id": "r", "role": "研究员", "task": "调研"},
            {
                "id": "s",
                "role": "学术审校员",
                "task": "审校",
                "depends_on": ["r"],
                "deliverable": {"name": "审校报告"},
            },
            {
                "id": "d",
                "role": "写手",
                "task": "成篇落盘",
                "deliverable": {"requires_files": True},
            },
        ],
        complexity_hint="standard",
    )
    assert errors == []
    for node in plan.nodes:
        assert node.token_ceiling == 600_000
        assert node.policy.timeout_s == WORKER_TIMEOUT_BACKSTOP_S


def test_build_plan_research_root_still_gets_research_retrieval():
    """检索预算机制不动：调研波 root 仍拿 research 检索额度。"""
    plan, errors = build_run_plan(
        [
            {
                "role": "数据研究员",
                "task": "深度调研并成篇汇报",
                "deliverable": {"form": "prose", "name": "调研报告"},
            }
        ],
        complexity_hint="standard",
    )
    assert errors == []
    node = plan.nodes[0]
    assert node.token_ceiling == 600_000
    assert node.policy.timeout_s == WORKER_TIMEOUT_BACKSTOP_S
    from agentcore.runtime.runs.retrieval_budget import DEFAULT_RETRIEVAL_BUDGET_RESEARCH

    assert node.retrieval_budget == DEFAULT_RETRIEVAL_BUDGET_RESEARCH


def test_explicit_timeout_ms_wins_over_backstop():
    plan, errors = build_run_plan(
        [
            {
                "id": "w1",
                "role": "写手",
                "task": "成篇落盘",
                "timeout_ms": 90_000,
                "deliverable": {"requires_files": True},
            }
        ],
        complexity_hint="standard",
    )
    assert errors == []
    node = plan.nodes[0]
    assert node.token_ceiling == 600_000
    assert node.policy.timeout_s == 90  # CEO 显式优先


def test_is_research_root_predicate():
    """共享判据（检索预算）：逐条件核对。"""
    assert is_research_root("standard", None, has_upstream=False, retrieval_budget=10)
    assert is_research_root("standard", None, has_upstream=False, retrieval_budget=None)
    assert not is_research_root("light", None, has_upstream=False, retrieval_budget=10)
    assert not is_research_root("standard", None, has_upstream=True, retrieval_budget=10)
    assert not is_research_root("standard", None, has_upstream=False, retrieval_budget=0)
    assert not is_research_root(
        "standard", Deliverable(requires_files=True), has_upstream=False, retrieval_budget=10
    )


def test_deep_deliverable_signals():
    assert is_deep_deliverable(Deliverable(form="files"))
    assert is_deep_deliverable(Deliverable(artifacts=["report.md"]))
    assert is_deep_deliverable(Deliverable(min_length=3_000))
    assert not is_deep_deliverable(Deliverable(min_length=500))
    assert not is_deep_deliverable(Deliverable(form="prose", name="短答"))
    assert not is_deep_deliverable(None)


def test_is_directed_search_role_covers_review_and_investigation():
    assert is_directed_search_role("后端核心审查员")
    assert is_directed_search_role("质检官")
    assert is_directed_search_role("调研员")
    assert is_directed_search_role("学术审校员")
    assert is_directed_search_role("code review")
    assert not is_directed_search_role("撰稿人")
    assert not is_directed_search_role("")


def test_ensure_directed_search_tools_enriches_restricted_allow_list():
    valid = {"file_list", "file_read", "grep", "code_search", "handoff"}
    enriched = ensure_directed_search_tools(
        ["file_list", "file_read"],
        role="前端审查员",
        valid_tools=valid,
    )
    assert enriched is not None
    assert "grep" in enriched
    assert "code_search" in enriched
    assert "file_read" in enriched
    assert (
        ensure_directed_search_tools(None, role="审查员", valid_tools=valid) is None
    )
    assert ensure_directed_search_tools(
        ["file_list"], role="撰稿人", valid_tools=valid
    ) == ["file_list"]
    assert frozenset({"grep", "code_search"}) == DIRECTED_SEARCH_TOOL_NAMES


def test_build_plan_enriches_reviewer_least_privilege_tools():
    plan, errors = build_run_plan(
        [
            {
                "role": "后端核心审查员",
                "task": "审查 server/app",
                "tools": ["file_list", "file_read"],
                "deliverable": {
                    "form": "prose",
                    "name": "审查意见",
                    "required_sections": ["问题", "建议", "评分"],
                },
            }
        ],
        valid_tools={"file_list", "file_read", "grep", "code_search", "handoff"},
    )
    assert errors == []
    tools = plan.nodes[0].tools
    assert tools is not None
    assert "grep" in tools
    assert "code_search" in tools
