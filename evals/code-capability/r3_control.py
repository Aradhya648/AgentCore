#!/usr/bin/env python3
"""R3 Collab · 无 LLM fixed/broken 对照 + 协作诊断字段基线报告.

Collab = 同一 Fix 题面强制/诱导 ``delegate``（复用 R1a seed）。
硬判据：测绿（与 Fix 同口径）；软：``collab_diagnostics``（run_plan / worker_files）不进 hard_accept。

对照：
  - broken：副本 + seed_patch → TestExitCode 须红；TestsUnchanged 须绿
  - fixed：干净 vendor（不打 seed）→ 硬 Check 全绿

用法（仓库根）::

    python evals/code-capability/r3_control.py --lint-only
    python evals/code-capability/r3_control.py --mode matrix
    python evals/code-capability/r3_control.py --mode fixed --task suites/r3/v01_collab_fix_int.json
    python evals/code-capability/r0_control.py --mode fixed   # R0 回归勿破
    python evals/code-capability/r1_control.py --lint-only    # R1 回归勿破
    python evals/code-capability/r2_control.py --lint-only    # R2 回归勿破

铁律：只对 copytree 隔离副本动手；seed_patch 只打副本；禁止写 vendor/。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
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
_SUITE_DIR = _CC_ROOT / "suites" / "r3"

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


def _resolve_seed(suite_dir: Path, seed_rel: str) -> Path:
    path = (suite_dir / seed_rel).resolve()
    if not path.is_file():
        raise SystemExit(f"seed_patch 不存在: {path}")
    return path


def _apply_seed(workspace: Path, suite_dir: Path, seed_rel: str) -> None:
    seed_path = _resolve_seed(suite_dir, seed_rel)
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
    dest = Path(tempfile.mkdtemp(prefix="agentcore-r3-"))
    shutil.copytree(vendor, dest, dirs_exist_ok=True)
    return dest


def _check_names(task: dict[str, Any]) -> list[str]:
    return [c.get("name") for c in (task.get("checks") or [])]


def _empty_collab_diagnostics(*, status: str = "pending", note: str = "") -> dict[str, Any]:
    """软诊断占位：无 LLM 时 pending；真跑后填 run_plan / worker_files。不进 hard_accept。"""
    return {
        "run_plan": None,
        "worker_files": None,
        "status": status,
        "note": note
        or "软维度占位（无 LLM）；不进 hard_accept。真跑后记 run_plan / worker 落盘。",
    }


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
        content="(r3_control no-LLM)",
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


def _verdict_collab_hard(mode: str, by_name: dict[str, bool]) -> tuple[bool, str]:
    """与 R1 Fix 同口径硬裁决；不含 collab 软诊断。"""
    if mode == "fixed":
        ok = all(by_name.values()) if by_name else False
        return ok, "fixed 硬过（干净 vendor）" if ok else "fixed 未全过"
    exit_ok = by_name.get("TestExitCode")
    tests_ok = by_name.get("TestsUnchanged", True)
    if exit_ok is True:
        return False, "broken 下 TestExitCode 竟通过——seed 闸失效"
    if not tests_ok:
        return False, "broken 下 TestsUnchanged 失败（seed 不应改测）"
    return True, "broken 对照有效（测失败 + TestsUnchanged 过）"


def cmd_lint(task_paths: list[Path]) -> int:
    from agentcore.evals.seed_lint import lint_case

    errors: list[str] = []
    for task_path in task_paths:
        task = _load_task(task_path)
        errors.extend(lint_case(task))
        tid = task.get("id")
        kind = (task.get("kind") or "").lower()
        if kind != "collab":
            errors.append(f"[{tid}] R3 卡 kind 须为 collab，得 {kind!r}")
        if (task.get("path") or "") != "team":
            errors.append(f"[{tid}] Collab 卡 path 须为 team")
        if (task.get("toolset") or "") != "ceo":
            errors.append(f"[{tid}] Collab 卡 toolset 须为 ceo（可 delegate）")
        seed = task.get("seed_patch")
        if not seed:
            errors.append(f"[{tid}] Collab 卡缺 seed_patch")
        else:
            sp = (_SUITE_DIR / seed).resolve()
            if not sp.is_file():
                errors.append(f"[{tid}] seed_patch 不存在: {sp}")
        vendor = task.get("vendor_dir")
        if vendor:
            vp = _VENDOR_ROOT / vendor
            if not vp.is_dir():
                errors.append(f"[{tid}] vendor_dir 不存在: {vp}")
            elif not (vp / "SOURCE.json").is_file():
                errors.append(f"[{tid}] SOURCE.json 缺失")
        names = _check_names(task)
        if "TestExitCode" not in names or "TestsUnchanged" not in names:
            errors.append(f"[{tid}] Collab 卡缺 TestExitCode/TestsUnchanged（硬闸）")
        collab = task.get("collab") or {}
        if not isinstance(collab, dict):
            errors.append(f"[{tid}] collab 须为对象")
        else:
            soft = collab.get("soft_diagnostics") or []
            for key in ("run_plan", "worker_files"):
                if key not in soft:
                    errors.append(f"[{tid}] collab.soft_diagnostics 须含 {key}")
        msg = (task.get("user_message") or "").lower()
        if "delegate" not in msg:
            errors.append(f"[{tid}] user_message 须诱导/强制 delegate")
    if errors:
        print("seed_lint FAIL:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"seed_lint OK: {len(task_paths)} tasks")
    return 0


def run_one(task_path: Path, mode: str) -> dict[str, Any]:
    task = _load_task(task_path)
    kind = (task.get("kind") or "collab").lower()
    vendor = _vendor_path(task)
    workspace = _copy_workspace(vendor)
    row: dict[str, Any] = {
        "id": task["id"],
        "vendor_id": task.get("vendor_id"),
        "kind": kind,
        "base_kind": task.get("base_kind", "fix"),
        "phase": task.get("phase", "R3"),
        "language": task.get("language"),
        "mode": mode,
        "task_path": str(task_path.relative_to(_CC_ROOT)).replace("\\", "/"),
        "pass": False,
        "fail_class": None,
        "detail": "",
        "checks": [],
        "collab_diagnostics": _empty_collab_diagnostics(),
    }
    try:
        # fixed = 干净 vendor；broken = 打 seed（与 R1 Fix 同）
        if mode != "fixed":
            seed = task.get("seed_patch")
            if not seed:
                raise SystemExit(f"{task['id']} 需要 seed_patch")
            _apply_seed(workspace, _SUITE_DIR, seed)

        results = _run_checks(task, workspace, reference=vendor)
        by_name: dict[str, bool] = {}
        check_rows = []
        for name, ok, detail in results:
            check_rows.append({"name": name, "passed": ok, "detail": detail[:300]})
            by_name[name] = ok
        row["checks"] = check_rows
        ok, msg = _verdict_collab_hard(mode, by_name)
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


def _llm_smoke_status() -> dict[str, Any]:
    key = os.environ.get("EVAL_DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return {
            "status": "pending",
            "note": "无 EVAL_DEEPSEEK_API_KEY；llm_smoke=pending 不挡 R3 硬验收",
        }
    if "--llm-smoke" in sys.argv:
        return {
            "status": "skipped_cost_guard",
            "note": "有 key 且请求了 --llm-smoke，但首期默认不烧；可手工绑 sidecar 抽 1 卡记诊断",
        }
    return {
        "status": "pending",
        "note": "检测到 eval key，但未跑 LLM（R3 硬验收仅 control 矩阵）",
    }


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
            diag = row.get("collab_diagnostics") or {}
            print(
                f"    collab_diagnostics: status={diag.get('status')} "
                f"run_plan={diag.get('run_plan')} worker_files={diag.get('worker_files')}"
            )
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
        "phase": "R3",
        "suite": "r3",
        "kind": "collab",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "control": "no-LLM fixed/broken matrix (Collab hard = Fix 同口径)",
        "llm_smoke": _llm_smoke_status(),
        "collab_diagnostics": {
            "schema": ["run_plan", "worker_files", "status", "note"],
            "soft": True,
            "hard_gate": False,
            "note": "每行 rows[].collab_diagnostics；首期无 LLM 为 pending/null；不进 hard_accept",
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
        for name in (f"r3_baseline_{stamp}.json", "r3_baseline_latest.json"):
            out = _REPORT_DIR / name
            out.write_text(text, encoding="utf-8")
            print(f"REPORT: {out.relative_to(_CC_ROOT).as_posix()}")

    print(
        f"VERDICT: matrix {'GREEN' if failed == 0 else 'RED'} "
        f"({report['summary']['pass']}/{len(rows)} cells · vendors={sorted(by_vendor)} · "
        f"langs={sorted(langs)})"
    )
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="R3 Collab 无 LLM 对照 / 基线报告")
    p.add_argument(
        "--mode",
        choices=("fixed", "broken", "matrix"),
        help="fixed|broken 单卡；matrix=全卡双对照并写报告",
    )
    p.add_argument("--lint-only", action="store_true")
    p.add_argument("--task", type=Path, help="单卡任务 JSON（相对 CC 根或绝对）")
    p.add_argument("--no-report", action="store_true", help="matrix 时不写报告文件")
    p.add_argument(
        "--llm-smoke",
        action="store_true",
        help="声明希望 LLM 烟感（有 key 时仍默认不烧；仅更新 llm_smoke 备注）",
    )
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
            raise SystemExit("无 R3 任务卡")

    if args.lint_only:
        return cmd_lint(tasks)

    if not args.mode:
        p.error("需要 --mode fixed|broken|matrix，或 --lint-only")

    if args.mode == "matrix":
        return cmd_matrix(tasks, write_report=not args.no_report)

    row = run_one(tasks[0], args.mode)
    mark = "PASS" if row["pass"] else "FAIL"
    print(f"[{mark}] {row['id']} {args.mode}: {row['detail']}")
    diag = row.get("collab_diagnostics") or {}
    print(
        f"  collab_diagnostics: status={diag.get('status')} "
        f"run_plan={diag.get('run_plan')} worker_files={diag.get('worker_files')}"
    )
    for c in row.get("checks") or []:
        m = "PASS" if c["passed"] else "FAIL"
        print(f"  [{m}] {c['name']}: {c['detail'][:200]}")
    return 0 if row["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
