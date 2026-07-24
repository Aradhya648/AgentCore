"""milestone 覆盖裁判 + 用例接入 + 结构校验 单测（后端架构.md §五）.

零真实 LLM：注入返回固定 JSON 的假 provider 验证 :class:`LLMMilestoneJudge` 的加权覆盖率 /
阈值 / 漏判保守按未覆盖 / 幻觉 id 忽略 / 坏 JSON 容错；用合成 ``TurnOutcome`` 验证 runner 接入
milestone 裁判并计入判定；纯函数验证 milestone 结构校验。真模型留给 nightly。
"""

import asyncio
import json

from agentcore.evals.judge import LLMMilestoneJudge
from agentcore.evals.report import report_to_dict
from agentcore.evals.runner import run_suite
from agentcore.evals.seed_lint import lint_case
from agentcore.evals.types import EvalCase, TurnOutcome
from agentcore.llm.provider.protocol import LLMResponse

# --- 假 milestone provider ---------------------------------------------------


class _MilestoneProvider:
    """返回固定 ``{items:[{id,covered}], rationale}`` 的假 provider（``calls`` 验调用数）。"""

    def __init__(self, covered: dict[str, bool], rationale: str = "r") -> None:
        self._covered = covered
        self._rationale = rationale
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001
        self.calls += 1
        items = [{"id": k, "covered": v} for k, v in self._covered.items()]
        return LLMResponse(content=json.dumps({"items": items, "rationale": self._rationale}))


class _GarbageProvider:
    async def complete(self, request):  # noqa: ANN001
        return LLMResponse(content="没有 JSON 的废话")


def _case_ms(milestones: list[dict], *, threshold: float = 0.8, **kw) -> EvalCase:
    base = {
        "id": "c",
        "category": "team",
        "user_message": "q",
        "milestones": milestones,
        "milestone_threshold": threshold,
    }
    base.update(kw)
    return EvalCase(**base)


def _outcome(content: str = "答案", **kw) -> TurnOutcome:
    base = {"content": content, "finish_reason": "end_turn", "rounds": 1}
    base.update(kw)
    return TurnOutcome(**base)


# --- LLMMilestoneJudge 加权覆盖 ----------------------------------------------


def test_milestone_all_covered_passes():
    ms = [{"id": "a", "desc": "da", "weight": 1}, {"id": "b", "desc": "db", "weight": 1}]
    judge = LLMMilestoneJudge(_MilestoneProvider({"a": True, "b": True}), "m")
    v = asyncio.run(judge.score_milestones(_case_ms(ms), _outcome()))
    assert v.coverage == 1.0
    assert v.passed is True
    assert len(v.items) == 2
    assert all(it.covered for it in v.items)


def test_milestone_weighted_partial_fails():
    ms = [
        {"id": "a", "desc": "x", "weight": 1},
        {"id": "b", "desc": "y", "weight": 1},
        {"id": "c", "desc": "z", "weight": 2},
    ]
    judge = LLMMilestoneJudge(_MilestoneProvider({"a": True, "b": True, "c": False}), "m")
    v = asyncio.run(judge.score_milestones(_case_ms(ms), _outcome()))
    assert v.coverage == 0.5  # 命中权重 2 / 总权重 4
    assert v.passed is False


def test_milestone_synthesis_weight_can_carry_pass():
    ms = [
        {"id": "a", "desc": "x", "weight": 1},
        {"id": "b", "desc": "y", "weight": 1},
        {"id": "c", "desc": "z", "weight": 2},
    ]
    # 漏了 a，但命中 b+c=3/4=0.75，阈值 0.75 → 过
    judge = LLMMilestoneJudge(_MilestoneProvider({"a": False, "b": True, "c": True}), "m")
    v = asyncio.run(judge.score_milestones(_case_ms(ms, threshold=0.75), _outcome()))
    assert v.coverage == 0.75
    assert v.passed is True


def test_milestone_missing_item_treated_uncovered():
    ms = [{"id": "a", "desc": "x", "weight": 1}, {"id": "b", "desc": "y", "weight": 1}]
    judge = LLMMilestoneJudge(_MilestoneProvider({"a": True}), "m")  # 裁判漏判 b
    v = asyncio.run(judge.score_milestones(_case_ms(ms), _outcome()))
    assert v.coverage == 0.5
    by = {it.id: it for it in v.items}
    assert by["b"].covered is False  # 漏判保守按未覆盖


def test_milestone_hallucinated_id_ignored():
    ms = [{"id": "a", "desc": "x", "weight": 1}]
    judge = LLMMilestoneJudge(_MilestoneProvider({"a": True, "zzz": True}), "m")
    v = asyncio.run(judge.score_milestones(_case_ms(ms), _outcome()))
    assert v.coverage == 1.0
    assert [it.id for it in v.items] == ["a"]  # 幻觉 id 不计入


def test_milestone_bad_json_all_uncovered_and_fails():
    ms = [{"id": "a", "desc": "x", "weight": 1}]
    judge = LLMMilestoneJudge(_GarbageProvider(), "m")
    v = asyncio.run(judge.score_milestones(_case_ms(ms), _outcome()))
    assert v.coverage == 0.0
    assert v.passed is False


def test_milestone_empty_trivially_passes():
    judge = LLMMilestoneJudge(_MilestoneProvider({}), "m")
    v = asyncio.run(judge.score_milestones(_case_ms([]), _outcome()))
    assert v.coverage == 1.0
    assert v.passed is True


# --- runner 接入（layer 2） --------------------------------------------------


class _OneOutcomeHarness:
    def __init__(self, outcome: TurnOutcome) -> None:
        self._oc = outcome

    async def run_case(self, case):  # noqa: ANN001
        return self._oc


def test_run_suite_attaches_milestone_and_gates_on_it():
    # L0 check 全过、但 milestone 覆盖不足 → CaseReport.passed=False（milestone 是结果维主轴）。
    harness = _OneOutcomeHarness(_outcome())
    case = _case_ms([{"id": "a", "desc": "x", "weight": 1}], checks=[{"name": "FinishReason"}])
    mj = LLMMilestoneJudge(_MilestoneProvider({"a": False}), "m")
    report = asyncio.run(run_suite([case], harness, milestone_judge=mj, layer=2))
    c = report.cases[0]
    assert c.milestone is not None and c.milestone.passed is False
    assert c.checks_passed is True  # L0 仍过
    assert c.passed is False  # 是 milestone 把它拉下来


def test_run_suite_layer1_skips_milestone():
    harness = _OneOutcomeHarness(_outcome())
    case = _case_ms([{"id": "a", "desc": "x", "weight": 1}], checks=[{"name": "FinishReason"}])
    prov = _MilestoneProvider({"a": False})
    report = asyncio.run(
        run_suite([case], harness, milestone_judge=LLMMilestoneJudge(prov, "m"), layer=1)
    )
    assert report.cases[0].milestone is None
    assert prov.calls == 0  # layer 1 不触发 milestone 裁判


def test_run_suite_milestone_pass_makes_case_pass():
    harness = _OneOutcomeHarness(_outcome())
    case = _case_ms([{"id": "a", "desc": "x", "weight": 1}], checks=[{"name": "FinishReason"}])
    mj = LLMMilestoneJudge(_MilestoneProvider({"a": True}), "m")
    report = asyncio.run(run_suite([case], harness, milestone_judge=mj, layer=2))
    assert report.cases[0].passed is True


def test_report_to_dict_includes_milestone():
    harness = _OneOutcomeHarness(_outcome())
    case = _case_ms([{"id": "a", "desc": "x", "weight": 1}], checks=[{"name": "FinishReason"}])
    mj = LLMMilestoneJudge(_MilestoneProvider({"a": True}), "m")
    report = asyncio.run(run_suite([case], harness, milestone_judge=mj, layer=2))
    m = report_to_dict(report)["cases"][0]["milestone"]
    assert m["passed"] is True
    assert m["coverage"] == 1.0
    assert m["items"][0]["id"] == "a"
    assert m["items"][0]["covered"] is True


# --- seed_lint milestone 结构校验 -------------------------------------------


def _raw(**kw) -> dict:
    base = {
        "id": "c",
        "category": "team",
        "user_message": "q",
        "checks": [{"name": "FinishReason"}],
    }
    base.update(kw)
    return base


def test_lint_milestones_valid():
    assert lint_case(_raw(milestones=[{"id": "a", "desc": "x", "weight": 2}])) == []


def test_lint_milestones_only_is_valid_judgment_source():
    raw = {
        "id": "c",
        "category": "team",
        "user_message": "q",
        "milestones": [{"id": "a", "desc": "x"}],
    }
    assert lint_case(raw) == []


def test_lint_no_checks_no_rubric_no_milestones_errors():
    raw = {"id": "c", "category": "team", "user_message": "q"}
    errs = lint_case(raw)
    assert any("不会判定任何东西" in e for e in errs)


def test_lint_milestones_not_list():
    assert any("milestones 须为列表" in e for e in lint_case(_raw(milestones="x")))


def test_lint_milestones_missing_id():
    assert any("缺 id" in e for e in lint_case(_raw(milestones=[{"desc": "x"}])))


def test_lint_milestones_duplicate_id():
    errs = lint_case(_raw(milestones=[{"id": "a", "desc": "x"}, {"id": "a", "desc": "y"}]))
    assert any("id 重复" in e for e in errs)


def test_lint_milestones_missing_desc():
    assert any("缺 desc" in e for e in lint_case(_raw(milestones=[{"id": "a"}])))


def test_lint_milestones_bad_weight():
    errs = lint_case(_raw(milestones=[{"id": "a", "desc": "x", "weight": 0}]))
    assert any("weight 须为正数" in e for e in errs)


def test_lint_milestone_threshold_out_of_range():
    errs = lint_case(_raw(milestones=[{"id": "a", "desc": "x"}], milestone_threshold=1.5))
    assert any("milestone_threshold" in e for e in errs)
