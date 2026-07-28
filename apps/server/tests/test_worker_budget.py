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
        assert node.token_ceiling == 1_000_000
        assert node.policy.timeout_s == WORKER_TIMEOUT_BACKSTOP_S


def test_build_plan_research_root_still_gets_research_retrieval():
    """非 prose worker 拿统一检索默认（与 token 硬顶同构）。"""
    plan, errors = build_run_plan(
        [
            {
                "role": "数据研究员",
                "task": "深度调研并成篇汇报",
                "deliverable": {"form": "files", "name": "调研报告", "artifacts": ["AgentCore/文档/research/r.md"]},
            }
        ],
        complexity_hint="standard",
    )
    assert errors == []
    node = plan.nodes[0]
    assert node.token_ceiling == 1_000_000
    assert node.policy.timeout_s == WORKER_TIMEOUT_BACKSTOP_S
    from agentcore.runtime.runs.retrieval_budget import DEFAULT_RETRIEVAL_BUDGET

    assert node.retrieval_budget == DEFAULT_RETRIEVAL_BUDGET


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
    assert node.token_ceiling == 1_000_000
    assert node.policy.timeout_s == 90  # CEO 显式优先


def test_is_research_root_predicate():
    """共享结构谓词（不再驱动检索默认分档）：逐条件核对。"""
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


def test_blocks_light_complexity_only_long_form():
    from agentcore.runtime.runs.worker_budget import blocks_light_complexity

    assert not blocks_light_complexity(Deliverable(form="files", artifacts=["a.py"]))
    assert not blocks_light_complexity(Deliverable(requires_files=True))
    assert blocks_light_complexity(Deliverable(min_length=3_000))
    assert not blocks_light_complexity(None)


def test_apply_light_round_budgets_stamps_max_rounds():
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunSpec
    from agentcore.runtime.runs.worker_budget import (
        LIGHT_REPAIR_MAX_ROUNDS,
        apply_light_round_budgets,
    )

    plan = RunPlan()
    plan.add(RunSpec(run_id="a", agent_id="a", agent_name="x", task="t", role="工程师"))
    apply_light_round_budgets(plan, complexity_hint="standard")
    assert plan.nodes[0].max_rounds is None
    apply_light_round_budgets(plan, complexity_hint="light")
    assert plan.nodes[0].max_rounds == LIGHT_REPAIR_MAX_ROUNDS


def test_zero_write_only_for_short_write_posture():
    """standard + files → zero_write off; light/repair stamped max_rounds → on."""
    from agentcore.runtime.engine.governance import create_loop_controller
    from agentcore.runtime.runs.worker_budget import (
        LIGHT_REPAIR_MAX_ROUNDS,
        is_short_write_posture,
        should_enable_zero_write,
    )

    assert not is_short_write_posture(max_rounds=None)
    assert is_short_write_posture(max_rounds=LIGHT_REPAIR_MAX_ROUNDS)
    assert is_short_write_posture(max_rounds=4)

    assert not should_enable_zero_write(files_expected=True, max_rounds=None)
    assert not should_enable_zero_write(
        files_expected=False, max_rounds=LIGHT_REPAIR_MAX_ROUNDS
    )
    assert should_enable_zero_write(
        files_expected=True, max_rounds=LIGHT_REPAIR_MAX_ROUNDS
    )
    assert should_enable_zero_write(files_expected=True, short_write_posture=True)
    assert not should_enable_zero_write(files_expected=True, short_write_posture=False)

    # create_loop_controller mirrors the gate (threshold from settings when on).
    off = create_loop_controller(
        frozenset({"file_read"}),
        files_expected=True,
        short_write_posture=False,
    )
    assert off.zero_write_finalize_rounds == 0
    on = create_loop_controller(
        frozenset({"file_read"}),
        files_expected=True,
        short_write_posture=True,
    )
    assert on.zero_write_finalize_rounds > 0


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


def test_repair_posture_keeps_browser_navigate():
    """light/repair 可抠 click / 全仓巡读，但必须保留 browser_navigate（开页任务）。"""
    from agentcore.runtime.runs.executor_node import (
        _REPAIR_POSTURE_WITHHOLD,
        _narrow_for_repair_posture,
    )
    from agentcore.tools.registry import ToolRegistry

    assert "browser_navigate" not in _REPAIR_POSTURE_WITHHOLD
    assert "browser_click" in _REPAIR_POSTURE_WITHHOLD
    allowed = [
        "browser_navigate",
        "browser_click",
        "browser_snapshot",
        "file_list",
        "read_url",
    ]
    _reg, narrowed = _narrow_for_repair_posture(ToolRegistry(), allowed)
    assert narrowed is not None
    assert "browser_navigate" in narrowed
    assert "browser_snapshot" in narrowed
    assert "browser_click" not in narrowed
    assert "file_list" not in narrowed
    assert "read_url" not in narrowed


def test_should_tighten_verify_exec_thrash_for_repair_verify_posture():
    """E3：修码验证短姿态启用收紧；files 短写仍走 zero_write，不平行造熔断器。"""
    from agentcore.runtime.engine.governance import create_loop_controller
    from agentcore.runtime.loop_controller import ToolAttempt
    from agentcore.runtime.runs.worker_budget import should_tighten_verify_exec_thrash

    # verify / diagnose：短预算 + 执行工具 + 非落盘 → tighten
    assert should_tighten_verify_exec_thrash(
        short_write_posture=True,
        files_expected=False,
        has_execution_tools=True,
    )
    # patch 落盘节点：zero_write，不 tighten
    assert not should_tighten_verify_exec_thrash(
        short_write_posture=True,
        files_expected=True,
        has_execution_tools=True,
    )
    # 无执行工具 / 非短姿态 → 不收紧
    assert not should_tighten_verify_exec_thrash(
        short_write_posture=True,
        files_expected=False,
        has_execution_tools=False,
    )
    assert not should_tighten_verify_exec_thrash(
        short_write_posture=False,
        files_expected=False,
        has_execution_tools=True,
    )

    tightened = create_loop_controller(
        frozenset({"code_execute", "file_read"}),
        files_expected=False,
        short_write_posture=True,
        tighten_verify_exec_thrash=True,
    )
    # Still the same LoopController — zero_write stays off for non-files verify.
    assert tightened.zero_write_finalize_rounds == 0
    # disable<=2：两次同工具失败即 disable（默认 3 才 disable）
    tightened.record(
        [ToolAttempt(fingerprint="fp0", tool_name="code_execute", success=False)]
    )
    assert not tightened.tool_circuit_breaker().disabled
    tightened.record(
        [ToolAttempt(fingerprint="fp1", tool_name="code_execute", success=False)]
    )
    assert tightened.tool_circuit_breaker().disabled == ("code_execute",)

    # unproductive threshold<=2：两轮无产出即 early stop（默认 3）
    tight_u = create_loop_controller(
        frozenset({"code_execute"}),
        files_expected=False,
        short_write_posture=True,
        tighten_verify_exec_thrash=True,
    )
    tight_u.note_round_productivity(
        had_tool_calls=True, all_failed=True, had_content=False
    )
    assert not tight_u.unproductive_early_stop()
    tight_u.note_round_productivity(
        had_tool_calls=True, all_failed=True, had_content=False
    )
    assert tight_u.unproductive_early_stop()

    baseline = create_loop_controller(
        frozenset({"code_execute"}),
        files_expected=False,
        short_write_posture=True,
        tighten_verify_exec_thrash=False,
    )
    for _ in range(2):
        baseline.note_round_productivity(
            had_tool_calls=True, all_failed=True, had_content=False
        )
    assert not baseline.unproductive_early_stop()
    baseline.note_round_productivity(
        had_tool_calls=True, all_failed=True, had_content=False
    )
    assert baseline.unproductive_early_stop()
