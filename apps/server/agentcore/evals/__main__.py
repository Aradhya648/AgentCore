"""评估体系 CLI（后端架构.md §五）：一条命令跑完整套评测、出报告.

用法::

    python -m agentcore.evals                  # core：L0 不变量 + L1 rubric 裁判（默认 layer 2）
    python -m agentcore.evals --layer 1        # 仅 L0 确定性 Check（无裁判，便宜）
    python -m agentcore.evals --out report.json
    python -m agentcore.evals --lint-only      # 只静态校验用例（零 LLM，per-PR 硬门禁）
    python -m agentcore.evals --update-baseline   # 落 baseline（回归门基准）后退出
    python -m agentcore.evals --baseline eval-out/core-baseline.json  # 跑回归门（跌破即非 0）
    python -m agentcore.evals --compare        # 对比评估：团队 vs 单体（成对裁判，诊断）
    python -m agentcore.evals --calibrate      # 裁判校准：gold-set 算判↔人 kappa（kappa<门 即非 0）

真跑（非 ``--lint-only``）会调真实 DeepSeek，需 ``EVAL_DEEPSEEK_API_KEY``。L1 绝对分裁判默认
固定 Pro 档（Pro 评 Flash，压同家族自偏好），可经 ``EVAL_JUDGE_MODEL`` 覆盖模型。
退出码：全过/未回归/裁判可信=0；用例未过、跌破 baseline 或 kappa<门=1；
配置/加载错误=2——便于挂 CI。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

from agentcore.core.log_context import bind_log_context
from agentcore.evals.calibration import (
    calibrate,
    calibration_to_dict,
    format_calibration_report,
    load_gold_set,
)
from agentcore.evals.comparison import (
    build_default_pairwise_judge,
    comparison_report_to_dict,
    format_comparison_report,
    load_comparison_cases,
    run_comparison_suite,
)
from agentcore.evals.debate_converge import (
    SCENARIOS,
    _debate_provider_and_model,
    debate_converge_to_dict,
    format_debate_converge_report,
    lint_scenarios,
    run_debate_converge,
)
from agentcore.evals.debate_speech_format import (
    SAMPLES as SPEECH_FORMAT_SAMPLES,
)
from agentcore.evals.debate_speech_format import (
    _debate_provider_and_model as _speech_format_provider_and_model,
)
from agentcore.evals.debate_speech_format import (
    debate_speech_format_to_dict,
    format_debate_speech_format_report,
    run_debate_speech_format,
)
from agentcore.evals.debate_speech_format import (
    lint_samples as lint_speech_format_samples,
)
from agentcore.evals.deliverable_form import (
    SAMPLES as DELIVERABLE_FORM_SAMPLES,
)
from agentcore.evals.deliverable_form import (
    _form_provider_and_model as _deliverable_form_provider_and_model,
)
from agentcore.evals.deliverable_form import (
    deliverable_form_to_dict,
    format_deliverable_form_report,
    run_deliverable_form,
)
from agentcore.evals.deliverable_form import (
    lint_samples as lint_deliverable_form_samples,
)
from agentcore.evals.judge import build_default_judge, build_default_milestone_judge
from agentcore.evals.report import baseline_regression, format_report, report_to_dict
from agentcore.evals.routing import (
    format_routing_report,
    routing_metrics,
    routing_metrics_to_dict,
)
from agentcore.evals.runner import load_cases, run_suite
from agentcore.evals.style_lint import (
    format_style_report,
    style_metrics,
    style_metrics_to_dict,
)
from agentcore.evals.types import EvalConfigError

# baseline 默认落盘到 apps/server/eval-out/（绝对路径，与 CLI 的 cwd 无关）。
_DEFAULT_EVAL_OUT = Path(__file__).resolve().parents[2] / "eval-out"

# gold-set 默认读包内 evals/cases/gold/labels.json（人工标注数据，随用例同放）。
_DEFAULT_GOLD_SET = Path(__file__).resolve().parent / "cases" / "gold" / "labels.json"


def _default_baseline_path(suite: str) -> Path:
    return _DEFAULT_EVAL_OUT / f"{suite}-baseline.json"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m agentcore.evals",
        description="AgentCore 离线评估：把黄金用例喂给真实运行路径，确定性断言出回归报告。",
    )
    p.add_argument("--suite", default="core", help="用例套件 cases/<suite>/*.json（默认 core）")
    p.add_argument(
        "--layer",
        type=int,
        default=2,
        choices=[1, 2],
        help="2=L0 不变量 + L1 rubric 裁判主轴（默认，需 key）；1=仅 L0 确定性 Check（无裁判）",
    )
    p.add_argument("--mode", default=None, help="覆盖所有用例的质量档：economy / quality / 自定义")
    p.add_argument(
        "--judge-mode",
        default="quality",
        help="裁判档（默认 quality→Pro，即 Pro 评 Flash；EVAL_JUDGE_MODEL 可覆盖）",
    )
    p.add_argument("--cases-dir", default=None, help="用例根目录（默认包内 cases/）")
    p.add_argument("--out", default=None, help="把 JSON 报告写到该路径（baseline / 回归对比用）")
    p.add_argument(
        "--baseline",
        default=None,
        help="baseline JSON 路径：存在则跑回归门（跌破即非 0）；配 --update-baseline 则写入",
    )
    p.add_argument(
        "--update-baseline",
        action="store_true",
        help="把报告写为 baseline 后退出（缺省 eval-out/<suite>-baseline.json）",
    )
    p.add_argument(
        "--regression-tolerance",
        type=float,
        default=0.05,
        help="回归门容差：当前 pass_rate < baseline-容差 才判回归（吸收真模型非确定性，默认 0.05）",
    )
    p.add_argument(
        "--lint-only",
        action="store_true",
        help="只做用例静态校验、不跑模型（零 LLM，per-PR 硬门禁）",
    )
    p.add_argument(
        "--plan-only",
        action="store_true",
        help=(
            "只规划不执行：真实 CEO 规划路径采 run_plan 后立刻收束（跳过 worker/辩论执行）；"
            "报告只看形状分；内容 Check/裁判标 n/a。与 --suite 组合（如 collab_shapes）"
        ),
    )
    p.add_argument(
        "--samples",
        type=int,
        default=None,
        help="覆盖所有用例的 samples（多采样取形状均值；缺省用用例 JSON 声明）",
    )
    p.add_argument(
        "--compare",
        action="store_true",
        help="对比评估（团队 vs 单体）：跑 cases/comparison/，成对裁判 + 三轴报告（nightly）",
    )
    p.add_argument(
        "--routing",
        action="store_true",
        help="路由准确率：跑 cases/routing/，确定性 Check + 混淆矩阵（CEO 自己做 vs 交团队）",
    )
    p.add_argument(
        "--style",
        action="store_true",
        help="输出风格违规：跑套件后对回复跑 anti-slop linter，出违规率（先可观测，方向④）",
    )
    p.add_argument(
        "--calibrate",
        action="store_true",
        help="裁判校准：人工 gold-set 过生产裁判，算判↔人 kappa（kappa>=门 才准上 baseline 门）",
    )
    p.add_argument(
        "--debate-converge",
        action="store_true",
        help="辩论收敛校准：合成场景过生产 _judge，量『裁判是否系统性过保守』（§三·诊断，不卡门）",
    )
    p.add_argument(
        "--debate-speech-format",
        action="store_true",
        help="辩手发言格式合规：直连 complete 量论点骨架纪律（无前言/无总标题/无加粗伪标题）",
    )
    p.add_argument(
        "--deliverable-form",
        action="store_true",
        help="交付形态 form=prose|files：直连 complete 量 CEO 看/用分流与落盘指示",
    )
    p.add_argument(
        "--gold-set",
        default=None,
        help="gold-set JSON 路径（缺省 evals/cases/gold/labels.json）；配 --calibrate 用",
    )
    p.add_argument(
        "--kappa-gate",
        type=float,
        default=0.6,
        help="kappa 门：Cohen's kappa(判↔人 pass/fail) >= 该值 才算裁判可信（默认 0.6）",
    )
    return p


async def _run_comparison(args: argparse.Namespace) -> int:
    """对比评估分支：跑 comparison 套件、成对裁判、按 archetype 分段报告。"""
    suite = args.suite if args.suite != "core" else "comparison"
    cases = load_comparison_cases(args.cases_dir, suite=suite)
    if args.mode:
        cases = [replace(c, mode=args.mode) for c in cases]

    if args.lint_only:
        print(f"[lint] OK — {len(cases)} 个对比用例结构合法（suite={suite}）")
        return 0

    judge = build_default_pairwise_judge()
    report = await run_comparison_suite(cases, judge=judge, layer=2)
    print(format_comparison_report(report))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(comparison_report_to_dict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")
    return 0  # 对比为软门禁（信息性），不以胜率卡退出码


async def _run_routing(args: argparse.Namespace) -> int:
    """路由准确率分支：跑 routing 套件、确定性 Check，再聚合混淆矩阵（方向③）。

    度量本身需真模型 CEO 回合（属已延后的 eval 主线）；故未过用例照 Layer 1 卡退出码，
    混淆矩阵为信息性附加视图。``--lint-only`` 时零 LLM、只校验用例结构（含路由标签唯一性）。
    """
    suite = args.suite if args.suite != "core" else "routing"
    cases = load_cases(args.cases_dir, suite=suite)
    if args.mode:
        cases = [replace(c, mode=args.mode) for c in cases]

    if args.lint_only:
        print(f"[lint] OK — {len(cases)} 个路由用例结构合法（suite={suite}）")
        return 0

    report = await run_suite(cases, judge=None, layer=1)
    print(format_report(report))
    metrics = routing_metrics(report.cases)
    print("\n" + format_routing_report(metrics))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(
                {"report": report_to_dict(report), "routing": routing_metrics_to_dict(metrics)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")

    return 0 if report.passed == report.total else 1


async def _run_style(args: argparse.Namespace) -> int:
    """风格违规分支：跑套件 → 对每条回复跑 anti-slop linter → 出违规率（方向④「先可观测」）.

    与 ``--routing`` 同构：linter 规则纯确定性、可零 LLM 单测，但**被检文本**需真模型回合
    产生，故出数仍挂在已延后的真跑评测主线上。报告为信息性（软门禁），不以违规率卡退出码。
    """
    cases = load_cases(args.cases_dir, suite=args.suite)
    if args.mode:
        cases = [replace(c, mode=args.mode) for c in cases]

    if args.lint_only:
        print(f"[lint] OK — {len(cases)} 个用例结构合法（suite={args.suite}）")
        return 0

    report = await run_suite(cases, judge=None, layer=1)
    metrics = style_metrics(report.cases)
    print(format_style_report(metrics))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(style_metrics_to_dict(metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")
    return 0  # 风格为软门禁（信息性），不以违规率卡退出码


async def _run_calibration(args: argparse.Namespace) -> int:
    """裁判校准分支：gold-set 过生产裁判 → 判↔人一致度 → kappa 门判可信（重设计 §五）。

    退出码：``kappa>=门``（裁判可信）=0；低于门=1（别拿这把没校准的尺子去卡 baseline 门）；
    gold-set 结构错误经 :class:`EvalConfigError` → 2。``--lint-only`` 零 LLM 只校验 gold-set 结构。
    """
    path = Path(args.gold_set) if args.gold_set else _DEFAULT_GOLD_SET
    labels = load_gold_set(path)

    if args.lint_only:
        print(f"[lint] OK — {len(labels)} 条 gold-set 标注结构合法（{path}）")
        return 0

    judge = build_default_judge(mode=args.judge_mode)
    result = await calibrate(judge, labels, kappa_gate=args.kappa_gate)
    print(format_calibration_report(result))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(calibration_to_dict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")

    return 0 if result.trustworthy else 1


async def _run_debate_converge(args: argparse.Namespace) -> int:
    """辩论收敛校准分支：合成场景过生产 `_judge` → 过保守/过早收敛率 + kappa（§三）。

    诊断性（非硬门禁）：目的是把「裁判是否系统性过保守」变成可复跑信号，故恒以退出码 0 返回
    （与 ``--compare`` / ``--style`` 同为信息性）。``--lint-only`` 零 LLM 只校验场景集结构；场景集
    结构错误经 :class:`EvalConfigError` → 2（由 :func:`main` 捕获）。真跑需
    ``EVAL_DEEPSEEK_API_KEY``。
    """
    lint_scenarios(SCENARIOS)
    if args.lint_only:
        print(f"[lint] OK — {len(SCENARIOS)} 个辩论收敛场景结构合法")
        return 0

    provider, model = _debate_provider_and_model(args.judge_mode)
    result = await run_debate_converge(provider, model, SCENARIOS)
    print(format_debate_converge_report(result))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(debate_converge_to_dict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")

    return 0  # 诊断信号，不以过保守率卡退出码（先量化再调，见 §三）


async def _run_debate_speech_format(args: argparse.Namespace) -> int:
    """辩手发言格式合规：成稿形态 draft_system + draft_brief → complete → 检查骨架。

    诊断性（与 ``--debate-converge`` 同）：``--lint-only`` 零 LLM；真跑出合规率与失败样例。
    """
    from agentcore.evals.debate_speech_format import (
        NOTES_DRAFT_SAMPLES,
        lint_notes_draft_samples,
    )

    lint_speech_format_samples(SPEECH_FORMAT_SAMPLES)
    lint_notes_draft_samples(NOTES_DRAFT_SAMPLES)
    if args.lint_only:
        print(
            f"[lint] OK — {len(SPEECH_FORMAT_SAMPLES)} 个成稿样本 + "
            f"{len(NOTES_DRAFT_SAMPLES)} 个合成笔记→成稿样本结构合法"
        )
        return 0

    provider, model = _speech_format_provider_and_model(args.judge_mode)
    result = await run_debate_speech_format(provider, model, SPEECH_FORMAT_SAMPLES)
    print(format_debate_speech_format_report(result))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(debate_speech_format_to_dict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")

    return 0


async def _run_deliverable_form(args: argparse.Namespace) -> int:
    """交付形态 form 分流：classifier system + 用户请求 → complete → 查 form / 落盘指示。

    诊断性：``--lint-only`` 零 LLM（含生产契约静态门禁）；真跑需 eval key。
    """
    lint_deliverable_form_samples(DELIVERABLE_FORM_SAMPLES)
    if args.lint_only:
        print(f"[lint] OK — {len(DELIVERABLE_FORM_SAMPLES)} 个交付形态样本 + 生产契约合法")
        return 0

    provider, model = _deliverable_form_provider_and_model(args.judge_mode)
    result = await run_deliverable_form(provider, model, DELIVERABLE_FORM_SAMPLES)
    print(format_deliverable_form_report(result))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(deliverable_form_to_dict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")

    return 0


async def _run(args: argparse.Namespace) -> int:
    if args.deliverable_form:
        return await _run_deliverable_form(args)
    if args.debate_speech_format:
        return await _run_debate_speech_format(args)
    if args.debate_converge:
        return await _run_debate_converge(args)
    if args.calibrate:
        return await _run_calibration(args)
    if args.compare:
        return await _run_comparison(args)
    if args.routing:
        return await _run_routing(args)
    if args.style:
        return await _run_style(args)

    cases = load_cases(args.cases_dir, suite=args.suite)
    if args.mode:
        cases = [replace(c, mode=args.mode) for c in cases]
    if args.samples is not None:
        if args.samples < 1:
            raise EvalConfigError("--samples 须 >= 1")
        cases = [replace(c, samples=args.samples) for c in cases]

    if args.lint_only:
        print(f"[lint] OK — {len(cases)} 个用例结构合法（suite={args.suite}）")
        return 0

    plan_only = bool(args.plan_only)
    # L1 主轴：layer>=2 时构造两类裁判（默认 Pro 评 Flash）——绝对分裁判按 case.rubric 给 1–5 分、
    # milestone 裁判按 case.milestones 判交付物覆盖；用例声明哪个就跑哪个，均计入判定。
    # plan-only 跳过内容裁判（形状才有意义）。
    judge = (
        None
        if plan_only
        else (build_default_judge(mode=args.judge_mode) if args.layer >= 2 else None)
    )
    milestone_judge = (
        None
        if plan_only
        else (
            build_default_milestone_judge(mode=args.judge_mode) if args.layer >= 2 else None
        )
    )
    report = await run_suite(
        cases,
        judge=judge,
        milestone_judge=milestone_judge,
        layer=1 if plan_only else args.layer,
        plan_only=plan_only,
    )
    if plan_only:
        print("[plan-only] 形状评测（内容 Check / 裁判均为 n/a）")
    print(format_report(report))

    if args.out:
        out = Path(args.out)
        out.write_text(
            json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n[report] 已写出 JSON -> {out}")

    # baseline：--update-baseline 写盘后退出；否则给定 --baseline 且文件存在则跑回归门。
    if args.update_baseline:
        path = Path(args.baseline) if args.baseline else _default_baseline_path(args.suite)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[baseline] 已更新 -> {path}")
        return 0

    exit_code = 0 if report.passed == report.total else 1
    if args.baseline:
        bpath = Path(args.baseline)
        if bpath.is_file():
            baseline = json.loads(bpath.read_text(encoding="utf-8"))
            regressed, detail = baseline_regression(report, baseline, args.regression_tolerance)
            print(f"[baseline] {detail}")
            if regressed:
                exit_code = 1
        else:
            print(f"[baseline] 未找到 {bpath}（跳过回归门；首跑用 --update-baseline 落基线）")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    # Synthetic batch traffic — filterable in logs/dev.jsonl (absence of ``traffic`` = real).
    bind_log_context(traffic="eval")
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except EvalConfigError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
