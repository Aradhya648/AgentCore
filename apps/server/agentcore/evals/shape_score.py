"""协作形状匹配度（阶段 1 评测主指标之一）.

对照剧本「中档默认形状」声明式期望，对 ``TurnOutcome.plan_runs``（来自 SSE ``run_plan``，
已过滤 captain）打 0~1 匹配分。定位是**报告指标**，不是 L0 硬门——与 Delegated /
RosterMatches 同属诊断哲学（见 ``checks.DIAGNOSTIC_CHECKS``）。

纯函数、零 LLM；期望形状键：

- ``min_workers`` / ``max_workers``：非 captain 节点数上下界
- ``parallel_fanout_min``：无依赖（扇出根）节点数下限
- ``has_join``：是否存在 ``depends_on`` ≥2 的汇入节点
- ``pipeline_depth_min``：最长依赖链长度（边数）下限
- ``pipeline_edges_min``：依赖边总数下限
- ``independent_reviewer``：是否存在独立审查/验证/对账角色（角色名关键词）
- ``has_nested``：是否存在 ``parent_run_id`` 非空的分组嵌套
- ``min_roles``：去重角色数下限
- ``plan_types``：允许的 ``plan_type`` 列表（如 ``["debate"]``）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 独立审查 / 验证 / 对账角色的启发式关键词（BYOK 下独立性=角色级，见提案 B6）。
_REVIEWER_ROLE = re.compile(
    r"审|校|验|查|对账|复核|红队|诊断|挑刺|质检|验证",
)


@dataclass(frozen=True)
class ShapeScoreResult:
    """一次形状匹配的结构化结果（总分 + 分项，便于报告与单测）。"""

    score: float
    details: dict[str, float] = field(default_factory=dict)
    summary: str = ""


def _worker_count(plan_runs: list[dict[str, Any]]) -> int:
    return len(plan_runs)


def _fanout_roots(plan_runs: list[dict[str, Any]]) -> int:
    return sum(1 for r in plan_runs if not (r.get("depends_on") or []))


def _has_join(plan_runs: list[dict[str, Any]]) -> bool:
    return any(len(r.get("depends_on") or []) >= 2 for r in plan_runs)


def _pipeline_depth(plan_runs: list[dict[str, Any]]) -> int:
    """最长依赖链的边数（DAG；忽略指向缺失节点的边）。"""
    by_id = {str(r["id"]): r for r in plan_runs if r.get("id")}
    memo: dict[str, int] = {}

    def depth(rid: str) -> int:
        if rid in memo:
            return memo[rid]
        node = by_id.get(rid)
        if not node:
            memo[rid] = 0
            return 0
        deps = [str(d) for d in (node.get("depends_on") or []) if d in by_id]
        if not deps:
            memo[rid] = 0
            return 0
        memo[rid] = 1 + max(depth(d) for d in deps)
        return memo[rid]

    return max((depth(str(r["id"])) for r in plan_runs if r.get("id")), default=0)


def _pipeline_edges(plan_runs: list[dict[str, Any]]) -> int:
    ids = {str(r["id"]) for r in plan_runs if r.get("id")}
    total = 0
    for r in plan_runs:
        total += sum(1 for d in (r.get("depends_on") or []) if str(d) in ids)
    return total


def _has_independent_reviewer(plan_runs: list[dict[str, Any]]) -> bool:
    for r in plan_runs:
        role = str(r.get("role") or "")
        if _REVIEWER_ROLE.search(role):
            return True
    return False


def _has_nested(plan_runs: list[dict[str, Any]]) -> bool:
    return any(r.get("parent_run_id") for r in plan_runs)


def _ratio(actual: float, minimum: float) -> float:
    if minimum <= 0:
        return 1.0
    return max(0.0, min(1.0, actual / minimum))


def score_shape(
    plan_runs: list[dict[str, Any]],
    expected: dict[str, Any] | None,
    *,
    plan_type: str | None = None,
) -> ShapeScoreResult:
    """对照声明式期望打 0~1 匹配分；无期望或空约束 → 1.0（无形状要求）。"""
    if not expected:
        return ShapeScoreResult(1.0, {}, "no expected_shape")
    # 声明了期望形状即隐含「该组队」：空计划直接 0 分，不让 max_workers 这类上界键被空计划
    # 「天然满足」而蹭分。
    if not plan_runs:
        return ShapeScoreResult(0.0, {}, "no plan (delegated=False)")

    details: dict[str, float] = {}
    workers = _worker_count(plan_runs)

    if "min_workers" in expected:
        details["min_workers"] = _ratio(workers, float(expected["min_workers"]))
    if "max_workers" in expected:
        mx = float(expected["max_workers"])
        details["max_workers"] = 1.0 if workers <= mx else _ratio(mx, workers)
    if "parallel_fanout_min" in expected:
        details["parallel_fanout_min"] = _ratio(
            _fanout_roots(plan_runs), float(expected["parallel_fanout_min"])
        )
    if "has_join" in expected:
        want = bool(expected["has_join"])
        details["has_join"] = 1.0 if _has_join(plan_runs) == want else 0.0
    if "pipeline_depth_min" in expected:
        details["pipeline_depth_min"] = _ratio(
            _pipeline_depth(plan_runs), float(expected["pipeline_depth_min"])
        )
    if "pipeline_edges_min" in expected:
        details["pipeline_edges_min"] = _ratio(
            _pipeline_edges(plan_runs), float(expected["pipeline_edges_min"])
        )
    if "independent_reviewer" in expected:
        want = bool(expected["independent_reviewer"])
        details["independent_reviewer"] = (
            1.0 if _has_independent_reviewer(plan_runs) == want else 0.0
        )
    if "has_nested" in expected:
        want = bool(expected["has_nested"])
        details["has_nested"] = 1.0 if _has_nested(plan_runs) == want else 0.0
    if "min_roles" in expected:
        n_roles = len({str(r.get("role") or "") for r in plan_runs if r.get("role")})
        details["min_roles"] = _ratio(n_roles, float(expected["min_roles"]))
    if "plan_types" in expected:
        allowed = {str(x) for x in (expected["plan_types"] or [])}
        details["plan_types"] = 1.0 if plan_type in allowed else 0.0

    if not details:
        return ShapeScoreResult(1.0, {}, "empty expected_shape")

    score = sum(details.values()) / len(details)
    parts = ", ".join(f"{k}={v:.2f}" for k, v in sorted(details.items()))
    return ShapeScoreResult(round(score, 4), details, parts)
