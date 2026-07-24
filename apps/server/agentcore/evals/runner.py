"""runner：加载用例 → 跑真实路径 → 确定性 Check（+可选裁判）→ 聚合 :class:`EvalReport`（§二）.

用例形态 = 数据（JSON）：``cases/<suite>/*.json``，每个文件是一个用例对象或对象列表。加载先经
:func:`agentcore.evals.seed_lint.lint_suite` 静态校验（用例写错立刻挂，per-PR 硬门禁复用此早
失败）。``samples>1`` 对「跑 Agent(+裁判)」整体重复，治非确定性（报告里同 case_id 多条）。
"""

from __future__ import annotations

import json
from pathlib import Path

from agentcore.core.logging import get_logger
from agentcore.evals.checks import DIAGNOSTIC_CHECKS, PLAN_ONLY_SHAPE_CHECKS, build_check
from agentcore.evals.harness import EvalHarness
from agentcore.evals.seed_lint import lint_suite
from agentcore.evals.shape_score import score_shape
from agentcore.evals.types import (
    CaseReport,
    CheckOutcome,
    EvalCase,
    EvalConfigError,
    EvalReport,
    Harness,
    Judge,
    MilestoneJudge,
    TurnOutcome,
)

logger = get_logger(__name__)

_DEFAULT_CASES_DIR = Path(__file__).parent / "cases"

# EvalCase 接受的字段（用例 JSON 里多出的键被忽略，便于加注释字段如 ``_note``）。
_CASE_FIELDS = frozenset(
    {
        "id",
        "category",
        "user_message",
        "path",
        "mode",
        "toolset",
        "workspace_fixture",
        "history",
        "checks",
        "rubric",
        "milestones",
        "milestone_threshold",
        "samples",
        "prompt_profile",
        "mast",
        "expected_shape",
    }
)


def _parse_case(raw: dict) -> EvalCase:
    return EvalCase(**{k: v for k, v in raw.items() if k in _CASE_FIELDS})


def load_raw_cases(cases_dir: Path, suite: str = "core") -> list[dict]:
    """读 ``cases_dir/suite/*.json`` 为原始 dict 列表（未 lint、未解析）。"""
    suite_dir = Path(cases_dir) / suite
    if not suite_dir.is_dir():
        raise EvalConfigError(f"用例套件目录不存在: {suite_dir}")
    raws: list[dict] = []
    for path in sorted(suite_dir.glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            raws.extend(loaded)
        else:
            raws.append(loaded)
    return raws


def load_cases(cases_dir: Path | str | None = None, suite: str = "core") -> list[EvalCase]:
    """加载 + lint + 解析一个套件的全部用例（lint 不过即 raise，绝不带病开跑）。"""
    base = Path(cases_dir) if cases_dir else _DEFAULT_CASES_DIR
    raws = load_raw_cases(base, suite)
    if not raws:
        raise EvalConfigError(f"套件 {suite!r} 没有任何用例（{base / suite}）")
    errors = lint_suite(raws)
    if errors:
        raise EvalConfigError("用例校验失败:\n  " + "\n  ".join(errors))
    return [_parse_case(r) for r in raws]


def apply_checks(
    case: EvalCase,
    outcome: TurnOutcome,
    *,
    plan_only: bool = False,
) -> list[CheckOutcome]:
    """对一次运行结果跑该用例声明的全部确定性 Check（判定零 LLM）。

    诊断 Check（``DIAGNOSTIC_CHECKS``，轨迹形状）落标 ``gating=False``：仍跑仍报告，但不计入
    pass/fail（后端架构.md §五）。

    ``plan_only``：内容类 Check 标 ``n/a (plan-only)`` 且 ``gating=False``；仅形状类
    （``PLAN_ONLY_SHAPE_CHECKS``）照常跑。
    """
    results: list[CheckOutcome] = []
    for spec in case.checks:
        name = str(spec.get("name", "?"))
        if plan_only and name not in PLAN_ONLY_SHAPE_CHECKS:
            results.append(
                CheckOutcome(name, True, "n/a (plan-only)", gating=False)
            )
            continue
        try:
            check = build_check(spec)
        except KeyError as e:  # 已被 lint 拦住；此处兜底，绝不让单个坏 check 炸整套
            results.append(CheckOutcome(name, False, f"未注册 check: {e}"))
            continue
        result = check.run(case, outcome)
        if result.name in DIAGNOSTIC_CHECKS:
            result.gating = False
        results.append(result)
    return results


async def run_case_report(
    case: EvalCase,
    harness: Harness,
    *,
    judge: Judge | None = None,
    milestone_judge: MilestoneJudge | None = None,
    layer: int = 1,
    plan_only: bool = False,
) -> list[CaseReport]:
    """跑一个用例 ``samples`` 次，每次产一条 :class:`CaseReport`（确定性 Check + 可选裁判）。

    ``layer>=2`` 时按用例声明接两类 L1 裁判：有 ``rubric`` 走绝对分 ``judge``、有 ``milestones``
    走覆盖 ``milestone_judge``（结果维，取代轨迹断言）。两者皆为判定信号，缺则跳过。

    ``plan_only``：跳过 judge / milestone（内容维无意义）；Check 仅保留形状类。
    """
    reports: list[CaseReport] = []
    for _ in range(max(1, case.samples)):
        outcome = await harness.run_case(case)
        checks = apply_checks(case, outcome, plan_only=plan_only)
        verdict = None
        milestone = None
        if not plan_only and layer >= 2 and outcome.error is None:
            if judge is not None and case.rubric:
                verdict = await judge.score(case, outcome)
            if milestone_judge is not None and case.milestones:
                milestone = await milestone_judge.score_milestones(case, outcome)
        shape_score = None
        if case.expected_shape is not None:
            shape_score = score_shape(
                outcome.plan_runs, case.expected_shape, plan_type=outcome.plan_type
            ).score
        reports.append(
            CaseReport(
                case_id=case.id,
                category=case.category,
                outcome=outcome,
                checks=checks,
                judge=verdict,
                milestone=milestone,
                mast=case.mast,
                shape_score=shape_score,
            )
        )
    return reports


async def run_suite(
    cases: list[EvalCase],
    harness: Harness | None = None,
    *,
    judge: Judge | None = None,
    milestone_judge: MilestoneJudge | None = None,
    layer: int = 1,
    plan_only: bool = False,
) -> EvalReport:
    """跑整套用例，聚合成 :class:`EvalReport`（一个用例 samples>1 时贡献多条）。"""
    runner_harness: Harness = harness or EvalHarness(plan_only=plan_only)
    all_reports: list[CaseReport] = []
    for case in cases:
        logger.info(
            "evals.case_start",
            case=case.id,
            category=case.category,
            path=case.path,
            samples=case.samples,
            plan_only=plan_only,
        )
        all_reports.extend(
            await run_case_report(
                case,
                runner_harness,
                judge=judge,
                milestone_judge=milestone_judge,
                layer=layer,
                plan_only=plan_only,
            )
        )
    return EvalReport(cases=all_reports)
