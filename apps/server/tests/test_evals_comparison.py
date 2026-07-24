"""对比评估骨架自测（后端架构 §五 多 Agent 对比 / per-PR 零 LLM 硬门禁）.

用**假 provider / 假 harness / 假裁判**零成本验证对比系统本身不坏，真模型留给 nightly。覆盖：
- 配对 runner：各臂采样、layer1 不裁判、pass^k 计算、subject_arms；
- 成对裁判 ``LLMPairwiseJudge``：干净 JSON 解析、**位置对调抵消位置偏见**、内容一致判同臂、
  坏 JSON 容错；
- 出错臂不调裁判直接判负；
- 度量与报告：胜率 / 成本比 / 延迟比、按 archetype 分段、JSON 序列化、控制台文本；
- ``seed_lint`` 对比用例分支（非法 archetype / 非法臂 / baseline 不在 arms / 未注册 check /
  既无 checks 也无 rubric / id 重复）。
"""

import asyncio
import json

from agentcore.evals.comparison import (
    archetype_breakdown,
    case_metrics,
    comparison_report_to_dict,
    format_comparison_report,
    run_comparison_case,
    run_comparison_suite,
)
from agentcore.evals.judge import LLMPairwiseJudge
from agentcore.evals.seed_lint import lint_comparison_case, lint_comparison_suite
from agentcore.evals.types import ComparisonCase, PairwiseVerdict, TurnOutcome
from agentcore.llm.provider.protocol import LLMResponse

# --- 假 harness / 裁判 provider / 裁判 ----------------------------------------


class _CmpHarness:
    """按运行路径返回预设 ``TurnOutcome``：team 更贵更快、含 [GOOD] 标记；single 更便宜更慢。"""

    def __init__(self, *, team_error: bool = False) -> None:
        self.team_error = team_error

    async def run_case(self, case) -> TurnOutcome:  # noqa: ANN001
        if case.path == "team":
            if self.team_error:
                return TurnOutcome(content="", finish_reason="error", rounds=0, error="boom")
            return TurnOutcome(
                content="团队答案 [GOOD]",
                finish_reason="end_turn",
                rounds=2,
                delegated=True,
                roster=["研究员", "撰稿人"],
                usage={"input": 200, "output": 100, "reasoning": 80},
                cost_usd=0.024,
                latency_ms=700,
            )
        return TurnOutcome(
            content="单体答案",
            finish_reason="end_turn",
            rounds=1,
            usage={"input": 80, "output": 40, "reasoning": 30},
            cost_usd=0.010,
            latency_ms=1000,
        )


class _BoNHarness:
    """single 臂逐次返回不同内容（第 2 条含 [GOOD]）、team 固定更贵——验证 best-of-N 选优。"""

    def __init__(self) -> None:
        self._singles = iter([f"单体{c}{' [GOOD]' if c == 'B' else ''}" for c in "ABCDEF"])

    async def run_case(self, case) -> TurnOutcome:  # noqa: ANN001
        if case.path == "team":
            return TurnOutcome(
                content="团队答案",
                finish_reason="end_turn",
                rounds=2,
                delegated=True,
                roster=["研究员"],
                usage={"input": 200, "output": 100, "reasoning": 80},
                cost_usd=0.024,
                latency_ms=700,
            )
        return TurnOutcome(
            content=next(self._singles),
            finish_reason="end_turn",
            rounds=1,
            usage={"input": 80, "output": 40, "reasoning": 30},
            cost_usd=0.010,
            latency_ms=1000,
        )


class _FixedJudgeProvider:
    """永远判给固定位置（X 或 Y）—— 模拟有位置偏见的裁判。"""

    def __init__(self, winner: str = "X", margin: int = 2) -> None:
        self.winner = winner
        self.margin = margin
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001
        self.calls += 1
        return LLMResponse(
            content=json.dumps({"winner": self.winner, "rationale": "r", "margin": self.margin})
        )


class _MarkerJudgeProvider:
    """按内容判：含 [GOOD] 的一方胜（与位置无关）—— 模拟无位置偏见的裁判。"""

    async def complete(self, request):  # noqa: ANN001
        text = request.messages[-1].content or ""
        xi, yi = text.find("【答案X】"), text.find("【答案Y】")
        xblock, yblock = text[xi:yi], text[yi:]
        if "[GOOD]" in xblock and "[GOOD]" not in yblock:
            w = "X"
        elif "[GOOD]" in yblock and "[GOOD]" not in xblock:
            w = "Y"
        else:
            w = "tie"
        return LLMResponse(content=json.dumps({"winner": w, "rationale": "marker", "margin": 1}))


class _GarbageJudgeProvider:
    async def complete(self, request):  # noqa: ANN001
        return LLMResponse(content="嗯……我觉得都还行吧，没有 JSON。")


class _TeamWinsJudge:
    """假成对裁判：主臂恒胜（验证 runner/度量，不碰真模型）。"""

    async def compare(self, *, subject_arm, **_kw):  # noqa: ANN001, ANN003
        return PairwiseVerdict(winner=subject_arm, rationale="stub", margin=2)


def _cmp_case(**over) -> ComparisonCase:
    base = dict(
        id="t_cmp",
        archetype="parallel_research",
        user_message="比较两种方案",
        arms=["single", "team"],
        baseline_arm="single",
        samples=2,
        checks={"single": [{"name": "FinishReason"}], "team": [{"name": "Delegated"}]},
        rubric="哪个更完整",
    )
    base.update(over)
    return ComparisonCase(**base)


# --- 配对 runner -------------------------------------------------------------


def test_run_comparison_case_aggregates_layer1():
    cc = _cmp_case(samples=3)
    rep = asyncio.run(run_comparison_case(cc, _CmpHarness(), layer=1))

    assert set(rep.arms) == {"single", "team"}
    assert len(rep.arms["single"].outcomes) == 3
    assert len(rep.arms["team"].outcomes) == 3
    assert rep.pairwise == {}  # layer1 不裁判
    assert rep.arms["single"].passk is True  # FinishReason 全过
    assert rep.arms["team"].passk is True  # Delegated 全过
    assert rep.subject_arms == ["team"]


# --- matched_single（等算力单体：best-of-N + 预算对齐 team）-------------------


def test_matched_single_iso_compute_arm_folds_and_budget_bounds():
    cc = _cmp_case(
        arms=["matched_single", "team"],
        baseline_arm="matched_single",
        checks={"matched_single": [{"name": "FinishReason"}], "team": [{"name": "Delegated"}]},
        samples=2,
    )
    rep = asyncio.run(run_comparison_case(cc, _CmpHarness(), judge=_TeamWinsJudge(), layer=2))

    ms = rep.arms["matched_single"]
    assert len(ms.outcomes) == 2
    o = ms.outcomes[0]
    # 预算 = team 思考-token 中位数 T_B=80；single 每次 30 → 累计 30/60/90≥80 → best-of-3
    assert abs(o.cost_usd - 0.030) < 1e-9  # 算力 = Σ尝试（钱并列报，0.010×3）
    assert o.usage["reasoning"] == 90  # 30 × 3（对齐轴：思考-token）
    assert o.usage["input"] == 240  # 80 × 3
    assert o.latency_ms == 1000  # max（best-of-N 可并行）
    assert o.delegated is False
    assert rep.subject_arms == ["team"]  # baseline=matched_single → 只检验 team
    comp = case_metrics(rep)["comparisons"]["team"]
    assert comp["cost_ratio"] == round(0.024 / 0.030, 4)  # ≈0.8：team compute ≈ 等算力单体


def test_matched_single_best_of_n_selects_champion():
    cc = _cmp_case(
        arms=["matched_single", "team"],
        baseline_arm="matched_single",
        checks={"matched_single": [{"name": "FinishReason"}], "team": [{"name": "Delegated"}]},
        samples=1,
    )
    judge = LLMPairwiseJudge(_MarkerJudgeProvider(), "m")  # 含 [GOOD] 的一方胜
    rep = asyncio.run(run_comparison_case(cc, _BoNHarness(), judge=judge, layer=2))

    champ = rep.arms["matched_single"].outcomes[0]
    assert "[GOOD]" in champ.content  # 擂台赛从 3 次尝试里选出含标记的最强一次
    assert abs(champ.cost_usd - 0.030) < 1e-9  # 仍按全部 3 次尝试累计算力


# --- 成对裁判 ----------------------------------------------------------------


def test_pairwise_judge_parses_clean_json_no_swap():
    judge = LLMPairwiseJudge(_FixedJudgeProvider(winner="X"), "m", swap=False)
    v = asyncio.run(
        judge.compare(
            rubric="r",
            user_message="q",
            subject_arm="team",
            subject_content="A",
            baseline_arm="single",
            baseline_content="B",
        )
    )
    assert v.winner == "team"  # X = 主臂
    assert v.margin == 2


def test_pairwise_judge_swap_cancels_position_bias():
    provider = _FixedJudgeProvider(winner="X")  # 永远选位置 X
    judge = LLMPairwiseJudge(provider, "m", swap=True)
    v = asyncio.run(
        judge.compare(
            rubric="r",
            user_message="q",
            subject_arm="team",
            subject_content="A",
            baseline_arm="single",
            baseline_content="B",
        )
    )
    assert v.winner == "tie"  # 正序判主臂、反序判基准 → 抵消为 tie
    assert provider.calls == 2


def test_pairwise_judge_consistent_winner_via_marker():
    judge = LLMPairwiseJudge(_MarkerJudgeProvider(), "m", swap=True)
    v = asyncio.run(
        judge.compare(
            rubric="r",
            user_message="q",
            subject_arm="team",
            subject_content="团队 [GOOD]",
            baseline_arm="single",
            baseline_content="单体",
        )
    )
    assert v.winner == "team"  # 两序都判含标记的一方 → 一致判主臂


def test_pairwise_judge_bad_json_is_tie():
    judge = LLMPairwiseJudge(_GarbageJudgeProvider(), "m", swap=False)
    v = asyncio.run(
        judge.compare(
            rubric="r",
            user_message="q",
            subject_arm="team",
            subject_content="A",
            baseline_arm="single",
            baseline_content="B",
        )
    )
    assert v.winner == "tie"
    assert "JSON" in v.rationale


# --- runner + 裁判 + 度量 ----------------------------------------------------


def test_run_comparison_case_metrics_with_judge():
    cc = _cmp_case(samples=4)
    rep = asyncio.run(run_comparison_case(cc, _CmpHarness(), judge=_TeamWinsJudge(), layer=2))
    m = case_metrics(rep)

    comp = m["comparisons"]["team"]
    assert comp["n"] == 4
    assert comp["wins"] == 4
    assert comp["win_rate"] == 1.0
    assert comp["cost_ratio"] == 2.4  # 0.024 / 0.010
    assert comp["latency_ratio"] == 0.7  # 700 / 1000
    assert m["arms"]["team"]["passk"] is True


def test_comparison_error_arm_loses_without_judge_call():
    cc = _cmp_case(samples=2)
    rep = asyncio.run(
        run_comparison_case(cc, _CmpHarness(team_error=True), judge=_TeamWinsJudge(), layer=2)
    )
    verdicts = rep.pairwise["team"]
    assert len(verdicts) == 2
    assert all(v.winner == "single" for v in verdicts)  # team 出错 → 基准胜（未调裁判）


def test_comparison_report_serializes_and_breaks_down():
    cc1 = _cmp_case(id="c1", archetype="parallel_research", samples=2)
    cc2 = _cmp_case(id="c2", archetype="simple", samples=2)
    report = asyncio.run(
        run_comparison_suite([cc1, cc2], _CmpHarness(), judge=_TeamWinsJudge(), layer=2)
    )

    data = comparison_report_to_dict(report)
    assert data["summary"]["total_cases"] == 2
    bd = data["summary"]["by_archetype"]
    assert bd["parallel_research"]["avg_win_rate"] == 1.0
    assert bd["simple"]["avg_win_rate"] == 1.0
    assert len(data["cases"]) == 2

    text = format_comparison_report(report)
    assert "对比评估报告" in text
    assert "parallel_research" in text

    # 直接验证 archetype_breakdown 与 dict 一致
    assert archetype_breakdown(report)["simple"]["cases"] == 1


# --- seed_lint 对比分支 ------------------------------------------------------


def _raw(**over) -> dict:
    base = {
        "id": "x",
        "archetype": "debate",
        "user_message": "q",
        "arms": ["single", "team"],
        "baseline_arm": "single",
        "rubric": "r",
    }
    base.update(over)
    return base


def test_lint_comparison_valid_case():
    assert lint_comparison_case(_raw()) == []


def test_lint_comparison_bad_archetype():
    assert any("archetype" in e for e in lint_comparison_case(_raw(archetype="nope")))


def test_lint_comparison_bad_arm():
    assert any("非法臂" in e for e in lint_comparison_case(_raw(arms=["single", "duo"])))


def test_lint_comparison_baseline_not_in_arms():
    errs = lint_comparison_case(_raw(arms=["single", "team"], baseline_arm="matched_single"))
    assert any("baseline_arm" in e for e in errs)


def test_lint_comparison_matched_single_requires_team():
    errs = lint_comparison_case(
        _raw(
            arms=["single", "matched_single"],
            baseline_arm="single",
            checks={"matched_single": [{"name": "FinishReason"}]},
        )
    )
    assert any("matched_single" in e and "team" in e for e in errs)


def test_lint_comparison_matched_single_with_team_ok():
    errs = lint_comparison_case(
        _raw(
            arms=["matched_single", "team"],
            baseline_arm="matched_single",
            checks={
                "matched_single": [{"name": "FinishReason"}],
                "team": [{"name": "Delegated"}],
            },
        )
    )
    assert errs == []


def test_lint_comparison_unregistered_check():
    errs = lint_comparison_case(_raw(checks={"team": [{"name": "Nope"}]}))
    assert any("未注册" in e for e in errs)


def test_lint_comparison_nothing_to_judge():
    errs = lint_comparison_case(_raw(rubric=None, checks={}))
    assert any("不会判定" in e for e in errs)


def test_lint_comparison_suite_dup_id():
    errs = lint_comparison_suite([_raw(id="a"), _raw(id="a")])
    assert any("id 重复" in e for e in errs)
