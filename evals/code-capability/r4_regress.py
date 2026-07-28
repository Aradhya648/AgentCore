#!/usr/bin/env python3
"""R4 真仓回归棘轮 · 冻结基线对比（默认不烧 LLM）.

相对 ``reports/baselines/r{1,2,3}.json``：pass_rate 回退 >10pp → 非零退出。
持平 / 更好 → 绿。bump 须 ``--update-baseline`` + ``--reason``。

用法（仓库根）::

    # 当前 latest 报告 vs 冻结基线（应绿；不重跑矩阵）
    python evals/code-capability/r4_regress.py --compare-latest

    # 指定报告对比
    python evals/code-capability/r4_regress.py --compare reports/r1_baseline_latest.json --phase r1

    # 跑无 LLM 矩阵后再比（可慢；可限相位）
    python evals/code-capability/r4_regress.py --run --phases r3
    python evals/code-capability/r4_regress.py --run --phases r0,r3

    # 只 lint（nightly / 抽测）
    python evals/code-capability/r4_regress.py --lint-only

    # 显式 bump（须理由）
    python evals/code-capability/r4_regress.py --update-baseline --phase r1 \\
      --from reports/r1_baseline_latest.json --reason "一句话理由"

模拟回退 Fail（单元测 / 本地一步）::

    python evals/code-capability/r4_regress.py --self-test-regression
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CC_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _CC_ROOT.parents[1]
_REPORT_DIR = _CC_ROOT / "reports"
_BASELINE_DIR = _REPORT_DIR / "baselines"
_MANIFEST_PATH = _BASELINE_DIR / "manifest.json"

# 规划棘轮：相对基线回退超过 10 个百分点 → Fail
DEFAULT_TOLERANCE_PP = 10.0

PHASES_WITH_BASELINE = ("r1", "r2", "r3")
ALL_PHASES = ("r0", "r1", "r2", "r3")

_CONTROL_CMDS: dict[str, list[str]] = {
    "r0": [sys.executable, str(_CC_ROOT / "r0_control.py"), "--mode", "fixed"],
    "r1": [
        sys.executable,
        str(_CC_ROOT / "r1_control.py"),
        "--suite",
        "all",
        "--mode",
        "matrix",
    ],
    "r2": [sys.executable, str(_CC_ROOT / "r2_control.py"), "--mode", "matrix"],
    "r3": [sys.executable, str(_CC_ROOT / "r3_control.py"), "--mode", "matrix"],
}

_LINT_CMDS: dict[str, list[str]] = {
    "r0": [sys.executable, str(_CC_ROOT / "r0_control.py"), "--lint-only"],
    "r1": [sys.executable, str(_CC_ROOT / "r1_control.py"), "--lint-only"],
    "r2": [sys.executable, str(_CC_ROOT / "r2_control.py"), "--lint-only"],
    "r3": [sys.executable, str(_CC_ROOT / "r3_control.py"), "--lint-only"],
}

_LATEST_REPORT: dict[str, Path] = {
    "r1": _REPORT_DIR / "r1_baseline_latest.json",
    "r2": _REPORT_DIR / "r2_baseline_latest.json",
    "r3": _REPORT_DIR / "r3_baseline_latest.json",
}


def pass_rate_from_report(report: dict[str, Any]) -> float:
    """从 R 真仓对照报告取 pass_rate（pass / matrix_cells；缺 cells 则 pass+fail）。"""
    summary = report.get("summary") or {}
    if "pass_rate" in summary:
        return float(summary["pass_rate"])
    passed = float(summary.get("pass", summary.get("passed", 0)))
    cells = summary.get("matrix_cells")
    if cells is None:
        failed = float(summary.get("fail", summary.get("failed", 0)))
        cells = passed + failed
    cells_f = float(cells)
    if cells_f <= 0:
        return 0.0
    return passed / cells_f


def compare_pass_rate(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    tolerance_pp: float = DEFAULT_TOLERANCE_PP,
) -> tuple[bool, str, float, float]:
    """对比 pass_rate。返回 ``(regressed, detail, cur, base)``。

    ``regressed`` 为 True 当且仅当 ``cur < base - tolerance_pp/100``。
    """
    cur = pass_rate_from_report(current)
    base = pass_rate_from_report(baseline)
    tol = float(tolerance_pp) / 100.0
    drop_pp = (base - cur) * 100.0
    regressed = cur < base - tol
    detail = (
        f"pass_rate {cur:.4f} ({cur * 100:.1f}%) vs baseline {base:.4f} ({base * 100:.1f}%)"
        f"；Δ={-drop_pp:+.1f}pp（容差 {tolerance_pp:g}pp）"
        f" → {'Fail 回归' if regressed else 'OK'}"
    )
    return regressed, detail, cur, base


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest() -> dict[str, Any]:
    if not _MANIFEST_PATH.is_file():
        return {"tolerance_pp": DEFAULT_TOLERANCE_PP, "phases": {}}
    return load_json(_MANIFEST_PATH)


def baseline_path(phase: str) -> Path:
    return _BASELINE_DIR / f"{phase}.json"


def tolerance_pp_from_manifest(manifest: dict[str, Any] | None = None) -> float:
    m = manifest if manifest is not None else load_manifest()
    return float(m.get("tolerance_pp", DEFAULT_TOLERANCE_PP))


def cmd_compare(
    phase: str,
    current_path: Path,
    *,
    tolerance_pp: float | None = None,
) -> int:
    bpath = baseline_path(phase)
    if not bpath.is_file():
        print(f"[r4] 缺少冻结基线: {bpath}", file=sys.stderr)
        return 2
    if not current_path.is_file():
        print(f"[r4] 缺少当前报告: {current_path}", file=sys.stderr)
        return 2
    tol = tolerance_pp if tolerance_pp is not None else tolerance_pp_from_manifest()
    current = load_json(current_path)
    baseline = load_json(bpath)
    regressed, detail, _cur, _base = compare_pass_rate(current, baseline, tolerance_pp=tol)
    print(f"[r4] {phase}: {detail}")
    print(f"     current={current_path.as_posix()}")
    print(f"     baseline={bpath.as_posix()}")
    return 1 if regressed else 0


def cmd_compare_latest(*, phases: list[str], tolerance_pp: float | None = None) -> int:
    exit_code = 0
    for phase in phases:
        if phase not in PHASES_WITH_BASELINE:
            print(f"[r4] skip {phase}（无冻结基线；R0 仅 --run / --lint-only）")
            continue
        code = cmd_compare(phase, _LATEST_REPORT[phase], tolerance_pp=tolerance_pp)
        if code != 0:
            exit_code = code
    return exit_code


def cmd_lint(phases: list[str]) -> int:
    for phase in phases:
        cmd = _LINT_CMDS.get(phase)
        if not cmd:
            print(f"[r4] 未知 phase: {phase}", file=sys.stderr)
            return 2
        print(f"[r4] lint {phase}: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=_REPO_ROOT)
        if proc.returncode != 0:
            return proc.returncode
    return 0


def cmd_run(phases: list[str], *, compare: bool = True) -> int:
    """跑无 LLM 对照；有基线的相位随后对比。"""
    exit_code = 0
    for phase in phases:
        cmd = _CONTROL_CMDS.get(phase)
        if not cmd:
            print(f"[r4] 未知 phase: {phase}", file=sys.stderr)
            return 2
        print(f"[r4] run {phase}: {' '.join(cmd)}")
        proc = subprocess.run(cmd, cwd=_REPO_ROOT)
        if proc.returncode != 0:
            print(f"[r4] {phase} control 非零退出 {proc.returncode}", file=sys.stderr)
            exit_code = proc.returncode
            continue
        if compare and phase in PHASES_WITH_BASELINE:
            code = cmd_compare(phase, _LATEST_REPORT[phase])
            if code != 0:
                exit_code = code
    return exit_code


def cmd_update_baseline(phase: str, source: Path, reason: str) -> int:
    reason = reason.strip()
    if not reason:
        print("[r4] --update-baseline 须提供非空 --reason（一句话）", file=sys.stderr)
        return 2
    if phase not in PHASES_WITH_BASELINE:
        print(f"[r4] 仅支持冻结相位 {PHASES_WITH_BASELINE}，got {phase!r}", file=sys.stderr)
        return 2
    if not source.is_file():
        print(f"[r4] 源报告不存在: {source}", file=sys.stderr)
        return 2

    _BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    dest = baseline_path(phase)
    payload = load_json(source)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = load_manifest()
    phases = dict(manifest.get("phases") or {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rel_source = source.resolve().relative_to(_CC_ROOT).as_posix()
    except ValueError:
        rel_source = source.as_posix()
    phases[phase] = {
        "file": f"{phase}.json",
        "source": rel_source,
        "frozen_at": now,
        "reason": reason,
    }
    manifest["schema"] = manifest.get("schema") or "r4_baselines_v1"
    manifest["tolerance_pp"] = manifest.get("tolerance_pp", DEFAULT_TOLERANCE_PP)
    manifest["phases"] = phases
    manifest["note"] = (
        "相对冻结基线 pass_rate 回退超过 tolerance_pp 个百分点 → Fail；"
        "须 --update-baseline + --reason"
    )
    _MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[r4] 已 bump 基线 {dest.as_posix()}")
    print(f"[r4] reason: {reason}")
    print(f"[r4] manifest → {_MANIFEST_PATH.as_posix()}")
    return 0


def cmd_self_test_regression() -> int:
    """演示 / 单测入口：合成回退 >10pp → 须 Fail；持平 → 绿。"""
    bpath = baseline_path("r1")
    if not bpath.is_file():
        print("[r4] self-test 需要 baselines/r1.json", file=sys.stderr)
        return 2
    baseline = load_json(bpath)
    same = deepcopy(baseline)
    regressed, detail, _, _ = compare_pass_rate(same, baseline, tolerance_pp=DEFAULT_TOLERANCE_PP)
    print(f"[r4] self-test 持平: {detail}")
    if regressed:
        print("[r4] self-test FAIL：持平竟判回归", file=sys.stderr)
        return 1

    dropped = deepcopy(baseline)
    summary = dropped.setdefault("summary", {})
    cells = int(summary.get("matrix_cells") or 100)
    # 回退 11pp（超过 10pp 容差）
    summary["pass"] = max(0, int(round(cells * (pass_rate_from_report(baseline) - 0.11))))
    summary["fail"] = cells - int(summary["pass"])
    summary.pop("pass_rate", None)
    regressed, detail, _, _ = compare_pass_rate(
        dropped, baseline, tolerance_pp=DEFAULT_TOLERANCE_PP
    )
    print(f"[r4] self-test 回退11pp: {detail}")
    if not regressed:
        print("[r4] self-test FAIL：回退 11pp 未判回归", file=sys.stderr)
        return 1

    mild = deepcopy(baseline)
    summary = mild.setdefault("summary", {})
    cells = int(summary.get("matrix_cells") or 100)
    # 回退 5pp（容差内）→ 绿
    summary["pass"] = max(0, int(round(cells * (pass_rate_from_report(baseline) - 0.05))))
    summary["fail"] = cells - int(summary["pass"])
    summary.pop("pass_rate", None)
    regressed, detail, _, _ = compare_pass_rate(mild, baseline, tolerance_pp=DEFAULT_TOLERANCE_PP)
    print(f"[r4] self-test 回退5pp: {detail}")
    if regressed:
        print("[r4] self-test FAIL：回退 5pp 不应 Fail", file=sys.stderr)
        return 1

    print("[r4] self-test OK（持平绿 · 11pp红 · 5pp绿）")
    return 0


def _parse_phases(raw: str | None, default: tuple[str, ...]) -> list[str]:
    if not raw:
        return list(default)
    parts = [p.strip().lower() for p in raw.replace(";", ",").split(",") if p.strip()]
    for p in parts:
        if p not in ALL_PHASES:
            raise SystemExit(f"未知 phase {p!r}；可选 {ALL_PHASES}")
    return parts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="R4 真仓回归棘轮（冻结基线 · 10pp）")
    p.add_argument(
        "--compare-latest",
        action="store_true",
        help="用 reports/r*_baseline_latest.json 对比冻结基线（演示绿）",
    )
    p.add_argument(
        "--compare",
        type=Path,
        default=None,
        help="指定当前报告 JSON 路径（须配 --phase）",
    )
    p.add_argument(
        "--phase",
        choices=PHASES_WITH_BASELINE,
        default=None,
        help="单相位（--compare / --update-baseline）",
    )
    p.add_argument(
        "--phases",
        default=None,
        help="逗号分隔相位：r0,r1,r2,r3（--run / --lint-only / --compare-latest）",
    )
    p.add_argument(
        "--run",
        action="store_true",
        help="跑无 LLM control 矩阵后对比（默认可含 r1,r2,r3；可加 r0）",
    )
    p.add_argument(
        "--lint-only",
        action="store_true",
        help="只跑各相位 seed_lint（不烧 LLM、不跑矩阵）",
    )
    p.add_argument(
        "--update-baseline",
        action="store_true",
        help="把 --from 报告写入冻结基线（须 --phase + --reason）",
    )
    p.add_argument("--from", dest="from_path", type=Path, default=None, help="bump 源报告")
    p.add_argument("--reason", default="", help="bump 一句话理由（强制）")
    p.add_argument(
        "--tolerance-pp",
        type=float,
        default=None,
        help=f"回退容差百分点（默认 manifest 或 {DEFAULT_TOLERANCE_PP:g}）",
    )
    p.add_argument(
        "--self-test-regression",
        action="store_true",
        help="本地/单测：合成回退触发 Fail 纪律",
    )
    args = p.parse_args(argv)

    modes = sum(
        bool(x)
        for x in (
            args.compare_latest,
            args.compare is not None,
            args.run,
            args.lint_only,
            args.update_baseline,
            args.self_test_regression,
        )
    )
    if modes != 1:
        p.error(
            "请恰好选一个："
            " --compare-latest | --compare | --run | --lint-only"
            " | --update-baseline | --self-test-regression"
        )

    if args.self_test_regression:
        return cmd_self_test_regression()

    if args.update_baseline:
        if not args.phase:
            p.error("--update-baseline 须 --phase")
        src = args.from_path or _LATEST_REPORT.get(args.phase)
        if src is None:
            p.error("--update-baseline 须 --from")
        return cmd_update_baseline(args.phase, src, args.reason)

    if args.lint_only:
        phases = _parse_phases(args.phases, default=ALL_PHASES)
        return cmd_lint(phases)

    if args.run:
        phases = _parse_phases(args.phases, default=PHASES_WITH_BASELINE)
        return cmd_run(phases)

    if args.compare is not None:
        if not args.phase:
            p.error("--compare 须 --phase")
        return cmd_compare(args.phase, args.compare, tolerance_pp=args.tolerance_pp)

    # --compare-latest
    phases = _parse_phases(args.phases, default=PHASES_WITH_BASELINE)
    return cmd_compare_latest(phases=phases, tolerance_pp=args.tolerance_pp)


if __name__ == "__main__":
    raise SystemExit(main())
