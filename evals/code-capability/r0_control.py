#!/usr/bin/env python3
"""R0 真仓脚手架 · 无 LLM 硬判据对照夹具.

用法（仓库根）::

    # 已修好对照：copytree vendor（无 seed）→ 硬 Check 须全过
    python evals/code-capability/r0_control.py --mode fixed

    # 故意未修：copytree + seed_patch → TestExitCode 须失败（闸有效）
    python evals/code-capability/r0_control.py --mode broken

    # 静态校验任务 JSON（复用 agentcore.evals.seed_lint）
    python evals/code-capability/r0_control.py --lint-only

铁律：只对 copytree 隔离副本动手；禁止写 vendor/ 源树。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_ROOT = _REPO_ROOT / "apps" / "server"
_CC_ROOT = Path(__file__).resolve().parent
_SUITE_DIR = _CC_ROOT / "suites" / "r0"
_VENDOR_ROOT = _CC_ROOT / "vendor"
_DEFAULT_TASK = _SUITE_DIR / "r0_fix_chunked.json"

# 让 ``agentcore.evals`` 可 import（不要求已 editable install）
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))


def _load_task(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _vendor_path(task: dict) -> Path:
    rel = task.get("vendor_dir") or ""
    root = _VENDOR_ROOT / rel
    if not root.is_dir():
        raise SystemExit(f"vendor 不存在: {root}")
    return root


def _apply_seed(workspace: Path, seed_rel: str) -> None:
    seed_path = _SUITE_DIR / seed_rel
    if not seed_path.is_file():
        raise SystemExit(f"seed_patch 不存在: {seed_path}")
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    if seed.get("format") != "replacements_v1":
        raise SystemExit(f"不支持的 seed format: {seed.get('format')!r}")
    for i, rep in enumerate(seed.get("replacements") or []):
        target = workspace / rep["path"]
        if not target.is_file():
            raise SystemExit(f"seed[{i}] 目标不存在: {target}")
        text = target.read_text(encoding="utf-8")
        old, new = rep["old"], rep["new"]
        if old not in text:
            raise SystemExit(f"seed[{i}] old 未命中: {rep['path']}")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")


def _copy_workspace(vendor: Path) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="agentcore-r0-"))
    # 勿把 SOURCE.json 当业务源；复制整树即可（SOURCE 在测目录外，无害）
    shutil.copytree(vendor, dest, dirs_exist_ok=True)
    return dest


def _run_checks(task: dict, workspace: Path, reference: Path) -> list[tuple[str, bool, str]]:
    from agentcore.evals.checks import build_check
    from agentcore.evals.types import EvalCase, TurnOutcome

    case = EvalCase(
        id=task["id"],
        category=task.get("category", "tool_use"),
        user_message=task.get("user_message", ""),
        path=task.get("path", "team"),
        mode=task.get("mode", "economy"),
        toolset=task.get("toolset", "ceo"),
        checks=list(task.get("checks") or []),
    )
    outcome = TurnOutcome(
        content="(r0_control no-LLM)",
        finish_reason="end_turn",
        rounds=0,
        workspace_root=str(workspace),
        reference_root=str(reference),
    )
    results: list[tuple[str, bool, str]] = []
    for spec in case.checks:
        co = build_check(spec).run(case, outcome)
        results.append((co.name, co.passed, co.detail))
    return results


def cmd_lint(task_path: Path) -> int:
    from agentcore.evals.seed_lint import lint_case

    task = _load_task(task_path)
    errors = lint_case(task)
    # 真仓扩展字段：seed / vendor 路径存在性
    seed = task.get("seed_patch")
    if seed:
        sp = _SUITE_DIR / seed
        if not sp.is_file():
            errors.append(f"[{task.get('id')}] seed_patch 不存在: {sp}")
    vendor = task.get("vendor_dir")
    if vendor:
        vp = _VENDOR_ROOT / vendor
        if not vp.is_dir():
            errors.append(f"[{task.get('id')}] vendor_dir 不存在: {vp}")
        src = vp / "SOURCE.json"
        if not src.is_file():
            errors.append(f"[{task.get('id')}] SOURCE.json 缺失: {src}")
    if errors:
        print("seed_lint FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"seed_lint OK: {task_path.name}")
    return 0


def cmd_control(mode: str, task_path: Path) -> int:
    task = _load_task(task_path)
    vendor = _vendor_path(task)
    # reference = vendor 源树（只读对照）；workspace = 隔离副本
    workspace = _copy_workspace(vendor)
    try:
        if mode == "broken":
            seed = task.get("seed_patch")
            if not seed:
                raise SystemExit("broken 模式需要 seed_patch")
            _apply_seed(workspace, seed)
        elif mode != "fixed":
            raise SystemExit(f"未知 mode={mode!r}")

        results = _run_checks(task, workspace, reference=vendor)
        print(f"mode={mode} workspace={workspace}")
        for name, ok, detail in results:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {name}: {detail[:200]}")

        by_name = {n: ok for n, ok, _ in results}
        if mode == "fixed":
            if all(ok for ok in by_name.values()):
                print("VERDICT: fixed 对照全过（硬判据 100%）")
                return 0
            print("VERDICT: fixed 对照未全过")
            return 1
        # broken：TestExitCode 必须失败；TestsUnchanged 仍应过（seed 不碰 tests）
        exit_ok = by_name.get("TestExitCode")
        tests_ok = by_name.get("TestsUnchanged", True)
        if exit_ok is True:
            print("VERDICT: broken 下 TestExitCode 竟通过——闸失效")
            return 1
        if not tests_ok:
            print("VERDICT: broken 下 TestsUnchanged 失败（seed 不应改测）")
            return 1
        print("VERDICT: broken 对照有效（TestExitCode 失败 + TestsUnchanged 过）")
        return 0
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="R0 code-capability 无 LLM 对照")
    p.add_argument(
        "--mode",
        choices=("fixed", "broken"),
        help="fixed=已修好副本；broken=植入缺陷副本",
    )
    p.add_argument("--lint-only", action="store_true", help="只跑 seed_lint")
    p.add_argument("--task", type=Path, default=_DEFAULT_TASK, help="任务 JSON 路径")
    args = p.parse_args(argv)

    if args.lint_only:
        return cmd_lint(args.task)
    if not args.mode:
        p.error("需要 --mode fixed|broken，或 --lint-only")
    return cmd_control(args.mode, args.task)


if __name__ == "__main__":
    raise SystemExit(main())
