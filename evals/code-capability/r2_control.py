#!/usr/bin/env python3
"""R2 Extend · 无 LLM fixed/broken 对照 + 基线报告.

Extend = 短需求续写 + 评测侧只追加 GOLDEN 测（不改 upstream 测）。
对照：
  - broken：副本 + GOLDEN（缺实现）→ TestExitCode 须红；TestsUnchanged（allow_extra）须绿
  - fixed：再打 reference_patch（参照实现）→ 硬 Check 全绿

用法（仓库根）::

    python evals/code-capability/r2_control.py --lint-only
    python evals/code-capability/r2_control.py --mode matrix
    python evals/code-capability/r2_control.py --mode fixed --task suites/r2/v01_extend_snake_case.json
    python evals/code-capability/r1_control.py --lint-only   # R1 回归勿破
    python evals/code-capability/r0_control.py --mode fixed  # R0 回归勿破

铁律：只对 copytree 隔离副本动手；禁止写 vendor/。
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
_SUITE_DIR = _CC_ROOT / "suites" / "r2"

if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))


def _load_task(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_tasks() -> list[Path]:
    if not _SUITE_DIR.is_dir():
        raise SystemExit(f"suite 目录不存在: {_SUITE_DIR}")
    return sorted(p for p in _SUITE_DIR.glob("*.json") if p.name != "manifest.json")


def _vendor_path(task: dict[str, Any]) -> Path:
    rel = task.get("vendor_dir") or ""
    root = _VENDOR_ROOT / rel
    if not root.is_dir():
        raise SystemExit(f"vendor 不存在: {root}")
    return root


def _apply_replacements(workspace: Path, suite_dir: Path, rel: str, *, label: str) -> None:
    path = suite_dir / rel
    if not path.is_file():
        raise SystemExit(f"{label} 不存在: {path}")
    seed = json.loads(path.read_text(encoding="utf-8"))
    if seed.get("format") != "replacements_v1":
        raise SystemExit(f"不支持的 {label} format: {seed.get('format')!r}")
    for i, rep in enumerate(seed.get("replacements") or []):
        target = workspace / rep["path"]
        if not target.is_file():
            raise SystemExit(f"{label}[{i}] 目标不存在: {target}")
        text = target.read_text(encoding="utf-8")
        old, new = rep["old"], rep["new"]
        if old not in text:
            raise SystemExit(f"{label}[{i}] old 未命中: {rep['path']}")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")


def _install_golden(workspace: Path, suite_dir: Path, task: dict[str, Any]) -> list[str]:
    """把 GOLDEN 测文件拷进副本；返回 dest 相对路径列表（posix）。"""
    dests: list[str] = []
    for i, item in enumerate(task.get("golden_tests") or []):
        src_rel = item.get("src") or ""
        dest_rel = item.get("dest") or ""
        if not src_rel or not dest_rel:
            raise SystemExit(f"golden_tests[{i}] 缺 src/dest")
        src = suite_dir / src_rel
        if not src.is_file():
            raise SystemExit(f"golden_tests[{i}] 源不存在: {src}")
        dest = workspace / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        dests.append(Path(dest_rel).as_posix())
    return dests


def _copy_workspace(vendor: Path) -> Path:
    dest = Path(tempfile.mkdtemp(prefix="agentcore-r2-"))
    shutil.copytree(vendor, dest, dirs_exist_ok=True)
    return dest


def _npm_install(workspace: Path, cache_prefix: str) -> None:
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


def _check_names(task: dict[str, Any]) -> list[str]:
    return [c.get("name") for c in (task.get("checks") or [])]


def _needs_test_exit(task: dict[str, Any]) -> bool:
    return "TestExitCode" in _check_names(task)


def _prep_workspace(task: dict[str, Any], workspace: Path) -> None:
    vid = task.get("vendor_id") or ""
    if vid == "V10" and _needs_test_exit(task):
        _npm_install(workspace, "zod-nm")
    elif vid == "V09":
        pass
    elif vid == "V08" and _needs_test_exit(task):
        # 预留：若后续加 V08 Extend
        _npm_install(workspace, "uuid-nm")


def _run_checks(
    task: dict[str, Any],
    workspace: Path,
    reference: Path,
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
        content="(r2_control no-LLM)",
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


def _verdict_extend(mode: str, by_name: dict[str, bool]) -> tuple[bool, str]:
    if mode == "fixed":
        ok = all(by_name.values()) if by_name else False
        return ok, "fixed 硬过（GOLDEN+参照实现）" if ok else "fixed 未全过"
    exit_ok = by_name.get("TestExitCode")
    tests_ok = by_name.get("TestsUnchanged", True)
    if exit_ok is True:
        return False, "broken 下 TestExitCode 竟通过——缺实现闸失效"
    if not tests_ok:
        return False, "broken 下 TestsUnchanged 失败（GOLDEN 白名单/upstream 测）"
    return True, "broken 对照有效（GOLDEN 红 + TestsUnchanged 过）"


def cmd_lint(task_paths: list[Path]) -> int:
    from agentcore.evals.seed_lint import lint_case

    errors: list[str] = []
    for task_path in task_paths:
        task = _load_task(task_path)
        errors.extend(lint_case(task))
        tid = task.get("id")
        kind = (task.get("kind") or "").lower()
        if kind != "extend":
            errors.append(f"[{tid}] R2 卡 kind 须为 extend，得 {kind!r}")
        goldens = task.get("golden_tests") or []
        if not goldens:
            errors.append(f"[{tid}] Extend 卡缺 golden_tests")
        for i, g in enumerate(goldens):
            src = g.get("src")
            dest = g.get("dest")
            if not src or not dest:
                errors.append(f"[{tid}] golden_tests[{i}] 缺 src/dest")
            elif not (_SUITE_DIR / src).is_file():
                errors.append(f"[{tid}] golden src 不存在: {src}")
        ref = task.get("reference_patch")
        if not ref:
            errors.append(f"[{tid}] Extend 卡缺 reference_patch")
        elif not (_SUITE_DIR / ref).is_file():
            errors.append(f"[{tid}] reference_patch 不存在: {ref}")
        vendor = task.get("vendor_dir")
        if vendor:
            vp = _VENDOR_ROOT / vendor
            if not vp.is_dir():
                errors.append(f"[{tid}] vendor_dir 不存在: {vp}")
            elif not (vp / "SOURCE.json").is_file():
                errors.append(f"[{tid}] SOURCE.json 缺失")
        names = _check_names(task)
        if "TestExitCode" not in names or "TestsUnchanged" not in names:
            errors.append(f"[{tid}] Extend 卡缺 TestExitCode/TestsUnchanged")
        # TestsUnchanged.allow_extra 须覆盖全部 golden dest
        allow: set[str] = set()
        for spec in task.get("checks") or []:
            if spec.get("name") == "TestsUnchanged":
                allow = {Path(p).as_posix() for p in (spec.get("args") or {}).get("allow_extra") or []}
        for g in goldens:
            dest = Path(g.get("dest") or "").as_posix()
            if dest and dest not in allow:
                errors.append(f"[{tid}] TestsUnchanged.allow_extra 未声明 GOLDEN dest: {dest}")
    if errors:
        print("seed_lint FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"seed_lint OK: {len(task_paths)} tasks")
    return 0


def run_one(task_path: Path, mode: str) -> dict[str, Any]:
    task = _load_task(task_path)
    kind = (task.get("kind") or "extend").lower()
    vendor = _vendor_path(task)
    workspace = _copy_workspace(vendor)
    row: dict[str, Any] = {
        "id": task["id"],
        "vendor_id": task.get("vendor_id"),
        "kind": kind,
        "phase": task.get("phase", "R2"),
        "language": task.get("language"),
        "mode": mode,
        "task_path": str(task_path.relative_to(_CC_ROOT)).replace("\\", "/"),
        "pass": False,
        "fail_class": None,
        "detail": "",
        "checks": [],
    }
    try:
        _prep_workspace(task, workspace)
        _install_golden(workspace, _SUITE_DIR, task)
        if mode == "fixed":
            ref_patch = task.get("reference_patch")
            if not ref_patch:
                raise SystemExit(f"{task['id']} fixed 需要 reference_patch")
            _apply_replacements(workspace, _SUITE_DIR, ref_patch, label="reference_patch")

        results = _run_checks(task, workspace, reference=vendor)
        by_name: dict[str, bool] = {}
        check_rows = []
        for name, ok, detail in results:
            check_rows.append({"name": name, "passed": ok, "detail": detail[:300]})
            by_name[name] = ok
        row["checks"] = check_rows
        ok, msg = _verdict_extend(mode, by_name)
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
    except Exception as e:  # noqa: BLE001
        row["pass"] = False
        row["fail_class"] = "control/harness"
        row["detail"] = f"exception: {type(e).__name__}: {e}"
        return row
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def cmd_matrix(task_paths: list[Path], write_report: bool) -> int:
    rows: list[dict[str, Any]] = []
    failed = 0
    for tp in task_paths:
        for mode in ("fixed", "broken"):
            print(f"== {tp.name} · {mode} ==")
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
    langs: set[str] = set()
    for r in rows:
        vid = r.get("vendor_id") or "?"
        slot = by_vendor.setdefault(vid, {"pass": 0, "fail": 0, "cards": 0})
        if r["mode"] == "fixed":
            slot["cards"] += 1
        if r["pass"]:
            slot["pass"] += 1
        else:
            slot["fail"] += 1
        if r.get("language"):
            langs.add(str(r["language"]).lower())

    report = {
        "phase": "R2",
        "suite": "r2",
        "kind": "extend",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "control": "no-LLM fixed/broken matrix (Extend)",
        "llm_smoke": {
            "status": "pending",
            "note": "无 EVAL key / 默认不烧 LLM；不挡 R2 硬验收",
        },
        "summary": {
            "tasks": len(task_paths),
            "matrix_cells": len(rows),
            "pass": sum(1 for r in rows if r["pass"]),
            "fail": failed,
            "hard_accept": failed == 0,
            "vendors": sorted(by_vendor.keys()),
            "vendor_count": len(by_vendor),
            "languages": sorted(langs),
            "cards_per_vendor_min": min((v["cards"] for v in by_vendor.values()), default=0),
        },
        "by_vendor": by_vendor,
        "rows": rows,
    }

    if write_report:
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        for name in (f"r2_baseline_{stamp}.json", "r2_baseline_latest.json"):
            out = _REPORT_DIR / name
            out.write_text(text, encoding="utf-8")
            print(f"REPORT: {out.relative_to(_CC_ROOT).as_posix()}")

    print(
        f"VERDICT: matrix {'GREEN' if failed == 0 else 'RED'} "
        f"({report['summary']['pass']}/{len(rows)} cells · vendors={sorted(by_vendor)} · langs={sorted(langs)})"
    )
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="R2 Extend 无 LLM 对照 / 基线报告")
    p.add_argument(
        "--mode",
        choices=("fixed", "broken", "matrix"),
        help="fixed|broken 单卡；matrix=全卡双对照并写报告",
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
        tasks = _discover_tasks()
        if not tasks:
            raise SystemExit("无 R2 任务卡")

    if args.lint_only:
        return cmd_lint(tasks)

    if not args.mode:
        p.error("需要 --mode fixed|broken|matrix，或 --lint-only")

    if args.mode == "matrix":
        return cmd_matrix(tasks, write_report=not args.no_report)

    row = run_one(tasks[0], args.mode)
    mark = "PASS" if row["pass"] else "FAIL"
    print(f"[{mark}] {row['id']} {args.mode}: {row['detail']}")
    for c in row.get("checks") or []:
        m = "PASS" if c["passed"] else "FAIL"
        print(f"  [{m}] {c['name']}: {c['detail'][:200]}")
    return 0 if row["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
