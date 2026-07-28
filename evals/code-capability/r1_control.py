#!/usr/bin/env python3
"""R1 Find+Fix · 无 LLM fixed/broken 对照 + 基线报告（R1a + R1b）.

用法（仓库根）::

    python evals/code-capability/r1_control.py --lint-only
    python evals/code-capability/r1_control.py --suite all --mode matrix
    python evals/code-capability/r1_control.py --suite r1a --mode matrix
    python evals/code-capability/r1_control.py --suite r1b --mode matrix
    python evals/code-capability/r1_control.py --mode fixed --task suites/r1b/v03_fix_url_eq.json
    python evals/code-capability/r0_control.py --mode fixed   # R0 回归勿破
    python evals/code-capability/r1a_control.py --mode matrix  # R1a 兼容入口

铁律：只对 copytree 隔离副本动手；seed_patch 只打副本；禁止写 vendor/。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_ROOT = _REPO_ROOT / "apps" / "server"
_CC_ROOT = Path(__file__).resolve().parent
_VENDOR_ROOT = _CC_ROOT / "vendor"
_REPORT_DIR = _CC_ROOT / "reports"
_SUITE_DIRS = {
    "r1a": _CC_ROOT / "suites" / "r1a",
    "r1b": _CC_ROOT / "suites" / "r1b",
}

if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))


def _load_task(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _suite_dir_for_task(task_path: Path) -> Path:
    """任务 JSON 所在 suite 目录（seeds 相对此目录）."""
    return task_path.resolve().parent


def _discover_tasks(suite: str) -> list[Path]:
    keys = list(_SUITE_DIRS) if suite == "all" else [suite]
    out: list[Path] = []
    for key in keys:
        root = _SUITE_DIRS[key]
        if not root.is_dir():
            if suite != "all":
                raise SystemExit(f"suite 目录不存在: {root}")
            continue
        out.extend(sorted(p for p in root.glob("*.json") if p.name != "manifest.json"))
    return out


def _vendor_path(task: dict[str, Any]) -> Path:
    rel = task.get("vendor_dir") or ""
    root = _VENDOR_ROOT / rel
    if not root.is_dir():
        raise SystemExit(f"vendor 不存在: {root}")
    return root


def _apply_seed(workspace: Path, suite_dir: Path, seed_rel: str) -> None:
    seed_path = suite_dir / seed_rel
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
    dest = Path(tempfile.mkdtemp(prefix="agentcore-r1-"))
    shutil.copytree(vendor, dest, dirs_exist_ok=True)
    return dest


def _npm_install(workspace: Path, cache_prefix: str) -> None:
    """在副本内准备 node_modules（跨卡缓存；不写入 vendor）."""
    lock = workspace / "package-lock.json"
    yarn = workspace / "yarn.lock"
    if lock.is_file():
        digest = hashlib.sha256(lock.read_bytes()).hexdigest()[:12]
    elif yarn.is_file():
        digest = hashlib.sha256(yarn.read_bytes()).hexdigest()[:12]
    else:
        digest = "nolock"
    cache_root = Path(tempfile.gettempdir()) / "agentcore-r1-cache" / f"{cache_prefix}-{digest}"
    nm = workspace / "node_modules"
    if nm.is_dir():
        return
    if (cache_root / "node_modules").is_dir():
        shutil.copytree(cache_root / "node_modules", nm)
        return
    # 优先 npm ci；zod 等仅有 yarn.lock 时退回 npm install
    cmds: list[list[str]] = []
    if lock.is_file():
        cmds.append(["npm", "ci", "--ignore-scripts"])
    cmds.append(["npm", "install", "--ignore-scripts"])
    last_err = ""
    for cmd in cmds:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            shell=os.name == "nt",
        )
        if proc.returncode == 0:
            break
        last_err = (proc.stderr or proc.stdout or "")[-800:]
    else:
        raise SystemExit(f"{cache_prefix} npm install 失败: {last_err}")
    cache_root.mkdir(parents=True, exist_ok=True)
    if (cache_root / "node_modules").exists():
        shutil.rmtree(cache_root / "node_modules", ignore_errors=True)
    shutil.copytree(nm, cache_root / "node_modules")


def _ensure_uuid_build(workspace: Path) -> None:
    """V08：npm + tsc → dist-node（Windows 勿依赖 bash build.sh）."""
    _npm_install(workspace, "uuid-nm")
    tsc = workspace / "node_modules" / ".bin" / ("tsc.cmd" if os.name == "nt" else "tsc")
    if not tsc.is_file():
        tsc_cmd = ["npx", "--no-install", "tsc", "-p", "tsconfig.json"]
    else:
        tsc_cmd = [str(tsc), "-p", "tsconfig.json"]
    proc = subprocess.run(
        tsc_cmd,
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        shell=os.name == "nt",
    )
    if proc.returncode != 0:
        raise SystemExit(f"uuid tsc 失败: {(proc.stderr or proc.stdout)[-800:]}")

    dist = workspace / "dist"
    dist_node = workspace / "dist-node"
    if not dist.is_dir():
        raise SystemExit("uuid tsc 未产出 dist/")
    if dist_node.exists():
        shutil.rmtree(dist_node)
    shutil.copytree(dist, dist_node)
    for f in dist_node.glob("*-browser*"):
        f.unlink(missing_ok=True)
    for f in dist_node.rglob("*.d.ts"):
        f.unlink(missing_ok=True)
    src_bin = workspace / "src" / "bin"
    if src_bin.is_dir():
        dest_bin = dist_node / "bin"
        if dest_bin.exists():
            shutil.rmtree(dest_bin)
        shutil.copytree(src_bin, dest_bin)


def _check_names(task: dict[str, Any]) -> list[str]:
    return [c.get("name") for c in (task.get("checks") or [])]


def _needs_test_exit(task: dict[str, Any]) -> bool:
    return "TestExitCode" in _check_names(task)


def _prep_workspace(task: dict[str, Any], workspace: Path) -> None:
    vid = task.get("vendor_id") or ""
    lang = (task.get("language") or "").lower()

    if vid == "V08" and _needs_test_exit(task):
        _ensure_uuid_build(workspace)
    elif vid == "V10" and _needs_test_exit(task):
        _npm_install(workspace, "zod-nm")
    elif vid == "V09":
        # commander 测为纯 JS node:test；无需 npm
        pass
    elif lang == "typescript" and vid not in ("V08", "V09", "V10") and _needs_test_exit(task):
        _npm_install(workspace, f"{vid.lower()}-nm")

    if vid == "V02" and _needs_test_exit(task):
        try:
            import httpx2  # noqa: F401
        except ImportError as e:
            raise SystemExit(
                "V02 starlette 需要 httpx2：pip install 'httpx2>=2.0.0'（评测机依赖，非 vendor）"
            ) from e


def _find_control_content(task: dict[str, Any], mode: str) -> str:
    """无 LLM：注入命中/未命中 gold 的合成回复，验证 ContentMatches 闸."""
    gold = task.get("gold") or {}
    paths = list(gold.get("paths") or [])
    symbols = list(gold.get("symbols") or [])
    if mode == "fixed":
        bits = ["Located the defect."]
        if paths:
            bits.append(f"File: {paths[0]}")
        if symbols:
            bits.append(f"Symbol: {symbols[0]}")
        return "\n".join(bits)
    return "I suspect the bug is in unrelated/module.py function other_fn."


def _run_checks(
    task: dict[str, Any],
    workspace: Path,
    reference: Path,
    *,
    content: str,
) -> list[tuple[str, bool, str]]:
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
        content=content,
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


def _verdict_fix(mode: str, by_name: dict[str, bool]) -> tuple[bool, str]:
    if mode == "fixed":
        ok = all(by_name.values()) if by_name else False
        return ok, "fixed 硬过" if ok else "fixed 未全过"
    exit_ok = by_name.get("TestExitCode")
    tests_ok = by_name.get("TestsUnchanged", True)
    if exit_ok is True:
        return False, "broken 下 TestExitCode 竟通过——闸失效"
    if not tests_ok:
        return False, "broken 下 TestsUnchanged 失败（seed 不应改测）"
    return True, "broken 对照有效（测失败 + TestsUnchanged 过）"


def cmd_lint(task_paths: list[Path]) -> int:
    from agentcore.evals.seed_lint import lint_case

    errors: list[str] = []
    for task_path in task_paths:
        task = _load_task(task_path)
        suite_dir = _suite_dir_for_task(task_path)
        errors.extend(lint_case(task))
        seed = task.get("seed_patch")
        if seed:
            sp = suite_dir / seed
            if not sp.is_file():
                errors.append(f"[{task.get('id')}] seed_patch 不存在: {sp}")
        vendor = task.get("vendor_dir")
        if vendor:
            vp = _VENDOR_ROOT / vendor
            if not vp.is_dir():
                errors.append(f"[{task.get('id')}] vendor_dir 不存在: {vp}")
            elif not (vp / "SOURCE.json").is_file():
                errors.append(f"[{task.get('id')}] SOURCE.json 缺失")
        kind = (task.get("kind") or "").lower()
        if kind == "find":
            gold = task.get("gold") or {}
            if not gold.get("paths") and not gold.get("symbols"):
                errors.append(f"[{task.get('id')}] Find 卡缺 gold.paths/symbols")
            names = _check_names(task)
            if "ContentMatches" not in names:
                errors.append(f"[{task.get('id')}] Find 卡缺 ContentMatches 硬闸")
        if kind == "fix":
            names = _check_names(task)
            if "TestExitCode" not in names or "TestsUnchanged" not in names:
                errors.append(f"[{task.get('id')}] Fix 卡缺 TestExitCode/TestsUnchanged")
    if errors:
        print("seed_lint FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"seed_lint OK: {len(task_paths)} tasks")
    return 0


def run_one(task_path: Path, mode: str) -> dict[str, Any]:
    task = _load_task(task_path)
    kind = (task.get("kind") or "fix").lower()
    suite_dir = _suite_dir_for_task(task_path)
    vendor = _vendor_path(task)
    workspace = _copy_workspace(vendor)
    row: dict[str, Any] = {
        "id": task["id"],
        "vendor_id": task.get("vendor_id"),
        "kind": kind,
        "phase": task.get("phase"),
        "mode": mode,
        "task_path": str(task_path.relative_to(_CC_ROOT)).replace("\\", "/"),
        "pass": False,
        "fail_class": None,
        "detail": "",
        "checks": [],
    }
    try:
        _prep_workspace(task, workspace)
        if kind == "fix" and mode == "fixed":
            pass
        else:
            seed = task.get("seed_patch")
            if not seed:
                raise SystemExit(f"{task['id']} 需要 seed_patch")
            _apply_seed(workspace, suite_dir, seed)
            # V08：seed 改 src 后需重建 dist-node
            if task.get("vendor_id") == "V08" and _needs_test_exit(task):
                _ensure_uuid_build(workspace)

        if kind == "find":
            content = _find_control_content(task, mode)
        else:
            content = "(r1_control no-LLM)"

        results = _run_checks(task, workspace, reference=vendor, content=content)
        by_name: dict[str, bool] = {}
        check_rows = []
        for name, ok, detail in results:
            check_rows.append({"name": name, "passed": ok, "detail": detail[:300]})
            by_name[name] = ok
        row["checks"] = check_rows

        if kind == "find":
            cm_flags = [c["passed"] for c in check_rows if c["name"] == "ContentMatches"]
            if mode == "fixed":
                ok = all(cm_flags) if cm_flags else False
                msg = "fixed gold 命中" if ok else "fixed gold 未全命中"
            else:
                ok = any(not v for v in cm_flags) if cm_flags else False
                msg = (
                    "broken 对照有效（gold 未命中）"
                    if ok
                    else "broken 下 ContentMatches 全过——Find 闸失效"
                )
            other_ok = all(
                c["passed"] for c in check_rows if c["name"] != "ContentMatches"
            )
            if mode == "fixed" and not other_ok:
                ok, msg = False, "fixed 非 ContentMatches check 失败"
        else:
            ok, msg = _verdict_fix(mode, by_name)

        row["pass"] = ok
        row["detail"] = msg
        if not ok:
            row["fail_class"] = "control/harness"
        return row
    except SystemExit as e:
        row["pass"] = False
        row["fail_class"] = "control/harness"
        row["detail"] = str(e)
        return row
    except Exception as e:  # noqa: BLE001 — 报告层吞住单卡异常
        row["pass"] = False
        row["fail_class"] = "control/harness"
        row["detail"] = f"exception: {type(e).__name__}: {e}"
        return row
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def cmd_matrix(task_paths: list[Path], write_report: bool, suite: str) -> int:
    rows: list[dict[str, Any]] = []
    failed = 0
    for tp in task_paths:
        for mode in ("fixed", "broken"):
            print(f"== {tp.parent.name}/{tp.name} · {mode} ==")
            row = run_one(tp, mode)
            rows.append(row)
            mark = "PASS" if row["pass"] else "FAIL"
            print(f"  [{mark}] {row['detail']}")
            for c in row.get("checks") or []:
                m = "PASS" if c["passed"] else "FAIL"
                print(f"    [{m}] {c['name']}: {c['detail'][:160]}")
            if not row["pass"]:
                failed += 1

    by_vendor: dict[str, dict[str, int]] = {}
    for r in rows:
        vid = r.get("vendor_id") or "?"
        slot = by_vendor.setdefault(vid, {"pass": 0, "fail": 0, "cards": 0})
        if r["mode"] == "fixed":
            slot["cards"] += 1
        if r["pass"]:
            slot["pass"] += 1
        else:
            slot["fail"] += 1

    phase = "R1" if suite == "all" else suite.upper().replace("R1", "R1")
    if suite == "r1a":
        phase = "R1a"
    elif suite == "r1b":
        phase = "R1b"
    else:
        phase = "R1"

    report = {
        "phase": phase,
        "suite": suite,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "control": "no-LLM fixed/broken matrix",
        "llm_smoke": {
            "status": "pending",
            "note": "无 EVAL_DEEPSEEK_API_KEY（或未请求 --llm-smoke）则跳过；不挡 R1 硬验收",
        },
        "summary": {
            "tasks": len(task_paths),
            "matrix_cells": len(rows),
            "pass": sum(1 for r in rows if r["pass"]),
            "fail": failed,
            "hard_accept": failed == 0,
            "vendors": sorted(by_vendor.keys()),
            "vendor_count": len(by_vendor),
        },
        "by_vendor": by_vendor,
        "rows": rows,
    }

    key = os.environ.get("EVAL_DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if key and "--llm-smoke-requested" in sys.argv:
        report["llm_smoke"] = {
            "status": "skipped_cost_guard",
            "note": "有 key 但 R1 默认不烧真跑；后续可手工抽 1–2 卡",
        }
    elif key:
        report["llm_smoke"] = {
            "status": "pending",
            "note": "检测到 eval key，但未跑 LLM（R1 硬验收仅 control 矩阵）",
        }

    if write_report:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        # 合并矩阵写 r1 + r1b latest；分波单独跑仍写对应文件
        if suite == "all":
            names = [
                f"r1_baseline_{stamp}.json",
                "r1_baseline_latest.json",
                f"r1b_baseline_{stamp}.json",
                "r1b_baseline_latest.json",
            ]
        elif suite == "r1b":
            names = [f"r1b_baseline_{stamp}.json", "r1b_baseline_latest.json"]
        else:
            names = [f"r1a_baseline_{stamp}.json", "r1a_baseline_latest.json"]
        for name in names:
            out = _REPORT_DIR / name
            out.write_text(text, encoding="utf-8")
            print(f"REPORT: {out.relative_to(_CC_ROOT).as_posix()}")

    print(
        f"VERDICT: matrix {'GREEN' if failed == 0 else 'RED'} "
        f"({report['summary']['pass']}/{len(rows)} cells · vendors={sorted(by_vendor)})"
    )
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="R1 code-capability 无 LLM 对照 / 基线报告")
    p.add_argument(
        "--mode",
        choices=("fixed", "broken", "matrix"),
        help="fixed|broken 单卡；matrix=全卡双对照并写报告",
    )
    p.add_argument(
        "--suite",
        choices=("r1a", "r1b", "all"),
        default="all",
        help="任务波次（默认 all=R1a+R1b）",
    )
    p.add_argument("--lint-only", action="store_true")
    p.add_argument("--task", type=Path, help="单卡任务 JSON（相对 CC 根或绝对）")
    p.add_argument("--no-report", action="store_true", help="matrix 时不写报告文件")
    args = p.parse_args(argv)

    if args.task:
        tp = args.task
        if not tp.is_file():
            alt = _CC_ROOT / tp
            if alt.is_file():
                tp = alt
            else:
                raise SystemExit(f"task 不存在: {args.task}")
        tasks = [tp]
    else:
        tasks = _discover_tasks(args.suite)
        if not tasks:
            raise SystemExit(f"无任务卡: suite={args.suite}")

    if args.lint_only:
        return cmd_lint(tasks)

    if not args.mode:
        p.error("需要 --mode fixed|broken|matrix，或 --lint-only")

    if args.mode == "matrix":
        return cmd_matrix(tasks, write_report=not args.no_report, suite=args.suite)

    row = run_one(tasks[0], args.mode)
    mark = "PASS" if row["pass"] else "FAIL"
    print(f"[{mark}] {row['id']} {args.mode}: {row['detail']}")
    for c in row.get("checks") or []:
        m = "PASS" if c["passed"] else "FAIL"
        print(f"  [{m}] {c['name']}: {c['detail'][:200]}")
    return 0 if row["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
