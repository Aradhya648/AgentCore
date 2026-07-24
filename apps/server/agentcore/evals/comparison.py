"""对比评估 runner（团队 vs 单体）—— 现状见 docs/02-架构/后端架构.md §五.

零侵入复用「功能评估」地基：为每个臂合成一个 :class:`EvalCase` 喂现有 :class:`EvalHarness`
（两条运行路径都已存在），再用 :class:`~agentcore.evals.types.PairwiseJudge` 成对裁判主臂
vs 基准臂，最后在「质量·成本·延迟」三轴上聚合，按 archetype 分段。

``single`` vs ``team`` 配对 + 成对裁判 + 三轴报告，全程可用假 provider / 假裁判跑通自测。
``matched_single``（等算力单体 best-of-N、按 team 的**思考-token 中位数**预算对齐）已落地——见
:func:`_run_matched_single_arm`：把「团队更好」从「砸了更多算力」纠正为「**同等算力下**更好」，
这是「多 Agent 是否真有价值」的关键判据。预算主单位 = 思考-token（钱/延迟并列报但不对齐），
是产品负责人已拍板的协议（远期规划 §2.4）。
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from agentcore.core.logging import get_logger
from agentcore.evals.harness import EvalHarness
from agentcore.evals.judge import LLMPairwiseJudge
from agentcore.evals.runner import apply_checks
from agentcore.evals.seed_lint import lint_comparison_suite
from agentcore.evals.types import (
    ArmResult,
    ComparisonCase,
    ComparisonCaseReport,
    ComparisonReport,
    EvalCase,
    EvalConfigError,
    Harness,
    PairwiseJudge,
    PairwiseVerdict,
    TurnOutcome,
    judged_text,
)

logger = get_logger(__name__)

_DEFAULT_CASES_DIR = Path(__file__).parent / "cases"

# 臂 → 运行路径。matched_single（等算力单体）也走 single 路径，但由本模块的 best-of-N +
# 预算对齐编排（见 _run_matched_single_arm），故同样映射到 "single"。
_ARM_TO_PATH: dict[str, str] = {
    "single": "single",
    "team": "team",
    "matched_single": "single",
}

# matched_single best-of-N 的安全上限：当单次 single 远比 team 便宜时，best-of-N 不会无限
# 采样烧额度（预算够即停，至多采样这么多次）。
_MATCHED_SINGLE_CAP = 6

_COMPARISON_FIELDS = frozenset(
    {
        "id",
        "archetype",
        "user_message",
        "arms",
        "baseline_arm",
        "mode",
        "toolset",
        "workspace_fixture",
        "history",
        "checks",
        "rubric",
        "samples",
    }
)


# --- 加载 + 解析 -------------------------------------------------------------


def _parse_comparison_case(raw: dict) -> ComparisonCase:
    return ComparisonCase(**{k: v for k, v in raw.items() if k in _COMPARISON_FIELDS})


def load_comparison_cases(
    cases_dir: Path | str | None = None, suite: str = "comparison"
) -> list[ComparisonCase]:
    """加载 + lint + 解析对比套件（lint 不过即 raise，绝不带病开跑）。"""
    base = Path(cases_dir) if cases_dir else _DEFAULT_CASES_DIR
    suite_dir = base / suite
    if not suite_dir.is_dir():
        raise EvalConfigError(f"对比用例套件目录不存在: {suite_dir}")
    raws: list[dict] = []
    for path in sorted(suite_dir.glob("*.json")):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        raws.extend(loaded if isinstance(loaded, list) else [loaded])
    if not raws:
        raise EvalConfigError(f"对比套件 {suite!r} 没有任何用例（{suite_dir}）")
    errors = lint_comparison_suite(raws)
    if errors:
        raise EvalConfigError("对比用例校验失败:\n  " + "\n  ".join(errors))
    return [_parse_comparison_case(r) for r in raws]


# --- 跑一道对比用例 ----------------------------------------------------------


def _arm_case(cc: ComparisonCase, arm: str) -> EvalCase:
    """把对比用例在某个臂上「投影」成一个普通 EvalCase（喂现有 harness）。"""
    path = _ARM_TO_PATH.get(arm, "single")
    return EvalCase(
        id=f"{cc.id}::{arm}",
        category="team" if path == "team" else "qa",
        user_message=cc.user_message,
        path=path,  # type: ignore[arg-type]
        mode=cc.mode,
        toolset=cc.toolset,
        workspace_fixture=cc.workspace_fixture,
        history=list(cc.history),
        checks=list(cc.checks.get(arm, [])),
        samples=1,  # 采样循环由本 runner 控制，harness 每次只跑一遍
    )


def _error_verdict(
    subject_arm: str, baseline_arm: str, s_oc: TurnOutcome, b_oc: TurnOutcome
) -> PairwiseVerdict:
    """任一臂出错时不调裁判：出错方判负，都错记 tie。"""
    s_err, b_err = bool(s_oc.error), bool(b_oc.error)
    if s_err and not b_err:
        return PairwiseVerdict(winner=baseline_arm, rationale=f"主臂出错: {s_oc.error}")
    if b_err and not s_err:
        return PairwiseVerdict(winner=subject_arm, rationale=f"基准臂出错: {b_oc.error}")
    return PairwiseVerdict(winner="tie", rationale="两臂均出错")


# --- matched_single：等算力单体（best-of-N + 预算对齐 team）-------------------


async def _best_of_n_single(
    cc: ComparisonCase, harness: Harness, budget_thinking: float
) -> list[TurnOutcome]:
    """按**思考-token 预算**反复跑「单体」一臂，累计思考-token 够到 ``budget_thinking`` 即停
    （至少 1 次、至多上限次）。

    预算主单位 = 思考-token（产品负责人已拍板：钱/延迟并列报但**不**对齐，见远期规划 §2.4）。
    顺序跑只为按实测累计思考-token 定 N（best-of-N 的 N 不预知）；返回每次尝试的 TurnOutcome。
    预算 ≤0（team 全 sample 无思考-token / 出错）→ 只跑 1 次，退化等价 single 臂。
    """
    ac = _arm_case(cc, "matched_single")
    attempts: list[TurnOutcome] = []
    cumulative = 0.0
    while len(attempts) < _MATCHED_SINGLE_CAP:
        outcome = await harness.run_case(ac)
        attempts.append(outcome)
        cumulative += float(outcome.usage.get("reasoning", 0))
        if cumulative >= budget_thinking:  # 预算够即停（overshoot ≤ 一次单体，刻意偏强基准）
            break
    return attempts


async def _select_champion(
    attempts: list[TurnOutcome],
    cc: ComparisonCase,
    *,
    judge: PairwiseJudge | None,
    layer: int,
) -> TurnOutcome:
    """best-of-N 选优：用成对裁判跑「擂台赛」选出最强一次尝试。

    有裁判（``layer>=2`` 且 ``cc.rubric``）才比质量——给单体它的**最好一击**，令对照基准尽可
    能强、team 的胜出更难被「单体没发挥好」解释（保守，宁可低估 team 优势）。无裁判 / 无
    rubric / 仅一条成功尝试时取第一条成功尝试（不凭空臆造质量排序）。
    """
    live = [a for a in attempts if not a.error]
    if not live:
        return attempts[0]  # 全失败：返回第一条（携带 error，交回上层按错判负）
    if len(live) == 1 or judge is None or layer < 2 or not cc.rubric:
        return live[0]
    champ = live[0]
    for challenger in live[1:]:
        verdict = await judge.compare(
            rubric=cc.rubric,
            user_message=cc.user_message,
            subject_arm="challenger",
            subject_content=judged_text(challenger),
            baseline_arm="champion",
            baseline_content=judged_text(champ),
        )
        if verdict.winner == "challenger":
            champ = challenger
    return champ


def _fold_matched_single(attempts: list[TurnOutcome], champion: TurnOutcome) -> TurnOutcome:
    """把 best-of-N 的多次尝试折叠成一个 matched_single 结果（喂现有成对裁判 / 三轴度量）。

    **质量取 champion**（选出的最强一次），**算力按全部尝试累加**（``usage`` 逐键求和含思考-
    token、``cost_usd`` 求和）——等算力的账 = N 次单体之和；**对齐轴是思考-token**（见
    :func:`_run_matched_single_arm`），钱/延迟并列入报但不作为对齐目标。**延迟取 max**：
    best-of-N 可并行采样、墙钟≈最慢一次（此处顺序跑仅为按预算定 N）。只要有一次成功就不算
    error。
    """
    usage: dict[str, int] = {}
    cost = 0.0
    for a in attempts:
        for k, v in a.usage.items():
            usage[k] = usage.get(k, 0) + int(v)
        cost += a.cost_usd
    live = [a for a in attempts if not a.error]
    return TurnOutcome(
        content=champion.content,
        finish_reason=champion.finish_reason,
        rounds=champion.rounds,
        tool_calls=list(champion.tool_calls),
        citations=list(champion.citations),
        delegated=False,
        roster=[],
        usage=usage,
        cost_usd=cost,
        latency_ms=max((a.latency_ms for a in attempts), default=0),
        error=None if live else (attempts[0].error if attempts else "matched_single 无任何尝试"),
        artifacts=dict(champion.artifacts),
    )


async def _run_matched_single_arm(
    cc: ComparisonCase,
    harness: Harness,
    team: ArmResult | None,
    *,
    judge: PairwiseJudge | None,
    layer: int,
) -> ArmResult:
    """跑 matched_single 臂：把单体 best-of-N 到 team 的**思考-token 中位数预算 T_B**。

    协议（产品负责人已拍板，见远期规划 §2.4）：预算主单位 = 思考-token；测量后对齐——先跑
    team、取思考-token 中位数 T_B、调 best-of-N 的 N 逼近 T_B。实际对齐度由报告的
    ``thinking_token_ratio``（team/matched）体现，落在 [0.8, 1.25] 即视为等算力（该带在取倒数
    下自封闭）。每 sample：按 T_B best-of-N → 选优 champion → 折叠成可与 team 逐对裁判的
    TurnOutcome；``checks`` 跑在折叠结果上（其 content / finish_reason 即 champion 的）。
    无 team → 预算 0、退化等价 single。
    """
    res = ArmResult(arm="matched_single")
    ac = _arm_case(cc, "matched_single")
    team_thinking = [float(o.usage.get("reasoning", 0)) for o in team.outcomes] if team else []
    budget = statistics.median(team_thinking) if team_thinking else 0.0
    for _ in range(max(1, cc.samples)):
        attempts = await _best_of_n_single(cc, harness, budget)
        champion = await _select_champion(attempts, cc, judge=judge, layer=layer)
        folded = _fold_matched_single(attempts, champion)
        res.outcomes.append(folded)
        res.checks.append(apply_checks(ac, folded))
    return res


async def run_comparison_case(
    cc: ComparisonCase,
    harness: Harness,
    *,
    judge: PairwiseJudge | None = None,
    layer: int = 1,
) -> ComparisonCaseReport:
    """跑一道对比用例：各臂采样 ``samples`` 次 → （layer≥2 且有裁判）主臂逐对 vs 基准臂。

    ``matched_single`` 臂特殊：先跑完 team 拿到思考-token 中位数预算，再据此 best-of-N 单体
    （见 :func:`_run_matched_single_arm`），故它总在 team 之后跑。
    """
    arms: dict[str, ArmResult] = {}
    # 先跑非 matched_single 臂（matched_single 的等算力预算取自 team 实测 compute，须后跑）。
    for arm in cc.arms:
        if arm == "matched_single":
            continue
        ac = _arm_case(cc, arm)
        res = ArmResult(arm=arm)
        for _ in range(max(1, cc.samples)):
            outcome = await harness.run_case(ac)
            res.outcomes.append(outcome)
            res.checks.append(apply_checks(ac, outcome))
        arms[arm] = res
    if "matched_single" in cc.arms:
        arms["matched_single"] = await _run_matched_single_arm(
            cc, harness, arms.get("team"), judge=judge, layer=layer
        )

    pairwise: dict[str, list[PairwiseVerdict]] = {}
    base = arms.get(cc.baseline_arm)
    if layer >= 2 and judge is not None and cc.rubric and base is not None:
        for arm in (a for a in cc.arms if a != cc.baseline_arm):
            subject = arms[arm]
            verdicts: list[PairwiseVerdict] = []
            n = min(len(subject.outcomes), len(base.outcomes))
            for i in range(n):
                s_oc, b_oc = subject.outcomes[i], base.outcomes[i]
                if s_oc.error or b_oc.error:
                    verdicts.append(_error_verdict(arm, cc.baseline_arm, s_oc, b_oc))
                    continue
                verdicts.append(
                    await judge.compare(
                        rubric=cc.rubric,
                        user_message=cc.user_message,
                        subject_arm=arm,
                        subject_content=judged_text(s_oc),
                        baseline_arm=cc.baseline_arm,
                        baseline_content=judged_text(b_oc),
                    )
                )
            pairwise[arm] = verdicts

    return ComparisonCaseReport(
        case_id=cc.id,
        archetype=cc.archetype,
        baseline_arm=cc.baseline_arm,
        arms=arms,
        pairwise=pairwise,
    )


async def run_comparison_suite(
    cases: list[ComparisonCase],
    harness: Harness | None = None,
    *,
    judge: PairwiseJudge | None = None,
    layer: int = 1,
) -> ComparisonReport:
    """跑整套对比用例，聚合成 :class:`ComparisonReport`。"""
    h: Harness = harness or EvalHarness()
    reports: list[ComparisonCaseReport] = []
    for cc in cases:
        logger.info(
            "evals.comparison_start",
            case=cc.id,
            archetype=cc.archetype,
            arms=cc.arms,
            samples=cc.samples,
        )
        reports.append(await run_comparison_case(cc, h, judge=judge, layer=layer))
    return ComparisonReport(cases=reports)


# --- 度量与报告（三轴 + 按 archetype 分段）----------------------------------


def _median(xs: list[float]) -> float | None:
    vals = [x for x in xs if x is not None]
    return statistics.median(vals) if vals else None


def _ratio(subj: list[float], base: list[float]) -> float | None:
    s, b = _median(subj), _median(base)
    if s is None or b is None or b == 0:
        return None
    return round(s / b, 4)


def _thinking(oc: TurnOutcome) -> float:
    return float(oc.usage.get("reasoning", 0))


def _total_tokens(oc: TurnOutcome) -> float:
    return float(oc.usage.get("input", 0) + oc.usage.get("output", 0))


def case_metrics(rep: ComparisonCaseReport) -> dict:
    """一道对比用例 → 可读/可序列化的度量 dict（各臂统计 + 主臂 vs 基准对比）。"""
    arms_m: dict[str, dict] = {}
    for arm, res in rep.arms.items():
        arms_m[arm] = {
            "samples": len(res.outcomes),
            "errors": sum(1 for o in res.outcomes if o.error),
            "passk": res.passk,
            "cost_usd_median": _median([o.cost_usd for o in res.outcomes]),
            "latency_ms_median": _median([float(o.latency_ms) for o in res.outcomes]),
            "tokens_median": _median([_total_tokens(o) for o in res.outcomes]),
            "thinking_tokens_median": _median([_thinking(o) for o in res.outcomes]),
        }

    comps: dict[str, dict] = {}
    base = rep.arms.get(rep.baseline_arm)
    for arm in rep.subject_arms:
        verdicts = rep.pairwise.get(arm, [])
        wins = sum(1 for v in verdicts if v.winner == arm)
        losses = sum(1 for v in verdicts if v.winner == rep.baseline_arm)
        ties = sum(1 for v in verdicts if v.winner == "tie")
        n = len(verdicts)
        subj = rep.arms[arm]
        comps[arm] = {
            "n": n,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "win_rate": round((wins + 0.5 * ties) / n, 4) if n else None,
            "cost_ratio": _ratio(
                [o.cost_usd for o in subj.outcomes],
                [o.cost_usd for o in base.outcomes] if base else [],
            ),
            "latency_ratio": _ratio(
                [float(o.latency_ms) for o in subj.outcomes],
                [float(o.latency_ms) for o in base.outcomes] if base else [],
            ),
            "thinking_token_ratio": _ratio(
                [_thinking(o) for o in subj.outcomes],
                [_thinking(o) for o in base.outcomes] if base else [],
            ),
        }

    return {
        "case_id": rep.case_id,
        "archetype": rep.archetype,
        "baseline_arm": rep.baseline_arm,
        "arms": arms_m,
        "comparisons": comps,
    }


def archetype_breakdown(report: ComparisonReport) -> dict[str, dict]:
    """按 archetype 聚合：团队（主臂）均胜率 + 均成本比（**不报全局单一胜率**）。"""
    by: dict[str, dict[str, list[float]]] = {}
    for rep in report.cases:
        m = case_metrics(rep)
        for c in m["comparisons"].values():
            if c["win_rate"] is None:
                continue
            bucket = by.setdefault(rep.archetype, {"win_rates": [], "cost_ratios": []})
            bucket["win_rates"].append(c["win_rate"])
            if c["cost_ratio"] is not None:
                bucket["cost_ratios"].append(c["cost_ratio"])
    out: dict[str, dict] = {}
    for arch, b in by.items():
        wr, cr = b["win_rates"], b["cost_ratios"]
        out[arch] = {
            "avg_win_rate": round(sum(wr) / len(wr), 4) if wr else None,
            "avg_cost_ratio": round(sum(cr) / len(cr), 4) if cr else None,
            "cases": len(wr),
        }
    return out


def comparison_report_to_dict(report: ComparisonReport) -> dict:
    """整套对比报告 → JSON-able dict（汇总 + 逐例），供落盘 / baseline 对比。"""
    return {
        "summary": {
            "total_cases": len(report.cases),
            "by_archetype": archetype_breakdown(report),
        },
        "cases": [case_metrics(r) for r in report.cases],
    }


def format_comparison_report(report: ComparisonReport) -> str:
    """控制台文本报告（逐例三轴 + 按 archetype 分段）。ASCII 标记避免 Windows 控制台乱码。"""
    lines: list[str] = ["=" * 64, "AgentCore 对比评估报告（团队 vs 单体）", "=" * 64]
    for rep in report.cases:
        m = case_metrics(rep)
        lines.append(f"[{rep.case_id}]  ({rep.archetype})  基准={rep.baseline_arm}")
        for arm, c in m["comparisons"].items():
            wr = f"{c['win_rate'] * 100:.0f}%" if c["win_rate"] is not None else "n/a"
            cr = f"{c['cost_ratio']:.2f}x" if c["cost_ratio"] is not None else "n/a"
            lr = f"{c['latency_ratio']:.2f}x" if c["latency_ratio"] is not None else "n/a"
            lines.append(
                f"    {arm} vs {rep.baseline_arm}: 胜率 {wr} "
                f"(W{c['wins']}-T{c['ties']}-L{c['losses']})  成本 {cr}  延迟 {lr}"
            )
        for arm, am in m["arms"].items():
            pk = "n/a" if am["passk"] is None else ("PASS" if am["passk"] else "FAIL")
            cost = am["cost_usd_median"] or 0.0
            lat = int(am["latency_ms_median"] or 0)
            lines.append(f"      - {arm}: pass^k={pk}  cost~${cost:.4f}  lat~{lat}ms")
    lines.append("-" * 64)
    for arch, b in sorted(archetype_breakdown(report).items()):
        awr = f"{b['avg_win_rate'] * 100:.0f}%" if b["avg_win_rate"] is not None else "n/a"
        acr = f"{b['avg_cost_ratio']:.2f}x" if b["avg_cost_ratio"] is not None else "n/a"
        lines.append(f"  {arch:<18} 团队均胜率 {awr}  均成本 {acr}  ({b['cases']} 例)")
    lines.append("=" * 64)
    return "\n".join(lines)


# --- 真模型裁判工厂（CLI/nightly 用；单测走注入的假裁判，不碰这里）-----------


def build_default_pairwise_judge(
    mode: str = "quality",
    *,
    ensemble: int | None = None,
) -> PairwiseJudge:
    """构造接真实 DeepSeek 的成对裁判：固定 Pro 档（§十一）。

    默认单裁判（``LLMPairwiseJudge``）。``ensemble`` 或环境变量 ``EVAL_JUDGE_ENSEMBLE``
    （整数 N≥2）时包装为 :class:`~agentcore.evals.judge.EnsemblePairwiseJudge`——N 个子裁判
    多数决；各子裁判默认仍开 swap，总成本至多 **2N** 次 LLM（接受的成本语义）。

    裁判模型优先读 ``EVAL_JUDGE_MODEL``，否则回落 ``mode`` 档（默认 quality）的 chat 档模型。
    凭据复用 harness 的 eval 专用 key 解析。仅 CLI/nightly 真跑调用——单测注入假裁判。
    """
    import os

    from agentcore.evals.eval_modes import resolve_profile_set
    from agentcore.evals.harness import _EVAL_CEILING, _eval_credentials
    from agentcore.evals.judge import EnsemblePairwiseJudge
    from agentcore.llm.factory import build_provider

    provider = build_provider(_eval_credentials())
    model = os.environ.get("EVAL_JUDGE_MODEL", "").strip()
    if not model:
        # Resolve against the FULL eval catalog ceiling (not the user ceiling, which
        # 内测 locked to Flash) so the default ``quality`` judge stays on Pro (§十一).
        profiles = resolve_profile_set(mode, custom_modes={}, ceiling=_EVAL_CEILING)
        model = profiles.model_for("chat")

    n = ensemble
    if n is None:
        raw = os.environ.get("EVAL_JUDGE_ENSEMBLE", "").strip()
        try:
            n = int(raw) if raw else 1
        except ValueError:
            n = 1
    n = max(1, n)

    if n == 1:
        return LLMPairwiseJudge(provider, model)

    judges = [LLMPairwiseJudge(provider, model) for _ in range(n)]
    return EnsemblePairwiseJudge(judges)
