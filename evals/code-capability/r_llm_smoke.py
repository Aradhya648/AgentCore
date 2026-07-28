#!/usr/bin/env python3
"""R 真仓 · LLM Agent sidecar 烟感（D 路径）.

流程：copytree vendor → apply seed → sidecar turn（user_message）→ 硬 Check → 报告。
复用 ``probe_sidecar_turn``（不改其 CLI）。禁止直绑 ``vendor/`` 写盘。

用法（``apps/server``）::

    uv run python ../../evals/code-capability/r_llm_smoke.py
    uv run python ../../evals/code-capability/r_llm_smoke.py --cards v07_fix_chunked,v01_fix_bool,v05_fix_has
    uv run python ../../evals/code-capability/r_llm_smoke.py --timeout 450

产物：``reports/llm_smoke_latest.json``；工作区副本在 ``workspaces/llm-smoke/<task_id>/``。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVER_ROOT = _REPO_ROOT / "apps" / "server"
_CC_ROOT = Path(__file__).resolve().parent
_VENDOR_ROOT = _CC_ROOT / "vendor"
_REPORT_DIR = _CC_ROOT / "reports"
_WS_ROOT = _CC_ROOT / "workspaces" / "llm-smoke"
_SUITE_DIRS = {
    "r1a": _CC_ROOT / "suites" / "r1a",
    "r1b": _CC_ROOT / "suites" / "r1b",
}

# 首波默认 Fix 卡（须含 V07 chunked）
_DEFAULT_CARD_STEMS = (
    "v07_fix_chunked",
    "v01_fix_bool",
    "v05_fix_has",
    "v01_fix_int",
)

if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))
if str(_CC_ROOT) not in sys.path:
    sys.path.insert(0, str(_CC_ROOT))

from probe_sidecar_turn import (  # noqa: E402
    AGENTCORE_ROOT_ID,
    DEFAULT_BASE_URL,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    SidecarClient,
    _auth,
    _has_run_plan,
    _mint_inference,
    _new_id,
    _setup_conversation,
)

OUT_DIR = _REPO_ROOT / "logs" / "probes"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unwrap_event(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize turn/event params: nested ``event`` or flat type/payload."""
    inner = params.get("event")
    if isinstance(inner, dict) and ("type" in inner or "payload" in inner):
        return {
            "type": inner.get("type"),
            "payload": inner.get("payload") or {},
            "turnId": params.get("turnId"),
        }
    return {
        "type": params.get("type"),
        "payload": params.get("payload") or {},
        "turnId": params.get("turnId"),
    }


def _resolve_card(stem: str) -> Path:
    stem = stem.strip()
    if not stem:
        raise SystemExit("空卡名")
    if stem.endswith(".json"):
        stem = Path(stem).stem
    direct = Path(stem)
    if direct.is_file():
        return direct.resolve()
    # 显式相对 CC 根
    under_cc = _CC_ROOT / stem
    if under_cc.is_file():
        return under_cc.resolve()
    candidates: list[Path] = []
    for suite_dir in _SUITE_DIRS.values():
        for p in suite_dir.glob("*.json"):
            if p.name == "manifest.json":
                continue
            if p.stem == stem or p.stem.endswith("_" + stem):
                candidates.append(p)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        # 优先 Fix 卡 / 完全后缀匹配
        preferred = [p for p in candidates if p.stem.endswith("_" + stem) and "_fix_" in p.stem]
        if len(preferred) == 1:
            return preferred[0]
        names = ", ".join(p.name for p in candidates)
        raise SystemExit(f"卡名歧义 {stem!r}: {names}")
    raise SystemExit(f"找不到任务卡: {stem}")


def _load_task(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _suite_dir(task_path: Path) -> Path:
    return task_path.resolve().parent


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


def _prepare_workspace(task: dict[str, Any], suite_dir: Path) -> tuple[Path, Path]:
    """copytree → 仓内隔离副本；返回 (workspace, vendor_ref)。"""
    vendor = _vendor_path(task)
    dest = _WS_ROOT / task["id"]
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(vendor, dest)
    seed = task.get("seed_patch")
    if seed:
        _apply_seed(dest, suite_dir, seed)
    return dest, vendor


def _run_hard_checks(
    task: dict[str, Any], workspace: Path, reference: Path
) -> list[dict[str, Any]]:
    from agentcore.evals.checks import build_check
    from agentcore.evals.types import EvalCase, TurnOutcome

    case = EvalCase(
        id=task["id"],
        category=task.get("category", "tool_use"),
        user_message=task.get("user_message", ""),
        path=task.get("path", "single"),
        mode=task.get("mode", "economy"),
        toolset=task.get("toolset", "ceo"),
        checks=list(task.get("checks") or []),
    )
    outcome = TurnOutcome(
        content="(r_llm_smoke post-turn)",
        finish_reason="end_turn",
        rounds=0,
        workspace_root=str(workspace),
        reference_root=str(reference),
    )
    rows: list[dict[str, Any]] = []
    for spec in case.checks:
        co = build_check(spec).run(case, outcome)
        rows.append({"name": co.name, "passed": co.passed, "detail": (co.detail or "")[:500]})
    return rows


def _classify_fail(
    *,
    error: str | None,
    finish: str | None,
    checks: list[dict[str, Any]] | None,
    checks_all_pass: bool,
    turn_started: bool = False,
    event_count: int = 0,
) -> str | None:
    if checks_all_pass and not error:
        return None
    err_l = (error or "").lower()
    fin = (finish or "").lower()

    if fin in {"ask_user", "plan_review", "paused", "needs_input", "suspended"}:
        return "需决策/交互"
    if error:
        # startTurn 已发出且无 finish：常见为 sidecar 在 proxy_spend 后挂起（接缝）
        if turn_started and ("timeout" in err_l or err_l.strip() == "" or "timed out" in err_l):
            return "接缝"
        if any(
            k in err_l
            for k in (
                "rate",
                "429",
                "quota",
                "connection",
                "refused",
                "initialize",
                "inference",
                "auth",
                "401",
                "403",
            )
        ):
            return "环境"
        if "sidecar" in err_l and not turn_started:
            return "环境"
        if "timeout" in err_l or "timed out" in err_l:
            return "环境"
        return "接缝"
    if checks:
        by = {c["name"]: c["passed"] for c in checks}
        if by.get("TestsUnchanged") is False and by.get("TestExitCode") is True:
            return "题面"  # 改了 tests/ 却测绿——题面/保护约束违例
        if by.get("TestExitCode") is False:
            return "模型弱"
        if not all(c["passed"] for c in checks):
            return "模型弱"
    return "模型弱"


async def _run_one_card(
    *,
    task_path: Path,
    base_url: str,
    user: str,
    password: str,
    root_id: str,
    timeout: float,
    max_resumes: int,
) -> dict[str, Any]:
    task = _load_task(task_path)
    suite_dir = _suite_dir(task_path)
    prompt = task.get("user_message") or ""
    if not prompt:
        return {
            "task_id": task.get("id"),
            "verdict": "fail",
            "fail_class": "题面",
            "error": "missing user_message",
        }

    workspace, vendor = _prepare_workspace(task, suite_dir)
    try:
        subpath = str(workspace.relative_to(_REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return {
            "task_id": task["id"],
            "verdict": "fail",
            "fail_class": "环境",
            "error": f"workspace 不在仓库树下，无法绑 root: {workspace}",
            "workspace": str(workspace),
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    data_dir = OUT_DIR / f"llm_smoke_data_{task['id']}_{ts}"
    data_dir.mkdir(parents=True, exist_ok=True)

    row: dict[str, Any] = {
        "task_id": task["id"],
        "task_path": str(task_path.relative_to(_CC_ROOT)).replace("\\", "/"),
        "vendor_id": task.get("vendor_id"),
        "vendor_dir": task.get("vendor_dir"),
        "kind": task.get("kind"),
        "language": task.get("language"),
        "workspace": str(workspace),
        "subpath": subpath,
        "conversation_id": None,
        "trace_id": None,
        "finish_reason": None,
        "run_plan": False,
        "tool_names": [],
        "elapsed_sec": None,
        "checks": None,
        "checks_pass": None,
        "verdict": "fail",
        "fail_class": None,
        "error": None,
        "notes": [],
    }

    conv_id: str | None = None
    folder_id: str | None = None
    inference: dict[str, str] | None = None
    user_id: str | None = None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            token, user_id = await _auth(client, base_url, user, password)
            inference = await _mint_inference(client, base_url, token)
            # 不回显 apiKey
            print(f"[{task['id']}] inference model={inference.get('model')}", flush=True)
            conv_id, folder_id = await _setup_conversation(
                client,
                base=base_url,
                token=token,
                title=f"llm-smoke-{task['id']}",
                root_id=root_id,
                local_subpath=subpath,
            )
    except Exception as e:
        row["error"] = str(e)
        row["fail_class"] = "环境"
        row["notes"].append("auth/inference/folder setup failed")
        return row

    row["conversation_id"] = conv_id
    row["folder_id"] = folder_id
    trace_id = uuid.uuid4().hex
    turn_id = _new_id()
    user_message_id = _new_id()
    row["trace_id"] = trace_id
    print(f"[{task['id']}] conversation_id={conv_id} trace_id={trace_id}", flush=True)
    print(f"[{task['id']}] workspace={workspace}", flush=True)

    sc = SidecarClient(workspace, data_dir)
    t0 = time.time()
    result: dict[str, Any] | None = None
    error: str | None = None
    finish: str | None = None
    turn_started = False

    try:
        await sc.start()
        if sc.proc is None or sc.proc.poll() is not None:
            raise RuntimeError("sidecar process exited immediately")
        init = await sc.initialize(user_id=user_id or "", inference=inference)
        if "error" in init:
            raise RuntimeError(f"initialize: {init['error']}")
        print(f"[{task['id']}] --- startTurn ---", flush=True)
        turn_started = True
        resp = await sc.start_turn(
            turn_id=turn_id,
            conversation_id=conv_id or "",
            user_message=prompt,
            trace_id=trace_id,
            user_message_id=user_message_id,
            inference=inference,
            timeout=timeout,
        )
        if "error" in resp:
            raise RuntimeError(str(resp["error"]))
        result = resp.get("result") or {}
        finish = result.get("finishReason") or result.get("finish_reason")
        print(f"[{task['id']}] startTurn finish={finish}", flush=True)

        # ask_user 等：默认不 resume 死等；记交互类失败
        resumes = 0
        while (
            resumes < max_resumes
            and isinstance(finish, str)
            and finish.lower() in {"ask_user", "plan_review", "paused", "needs_input", "suspended"}
        ):
            mid = result.get("messageId") or result.get("message_id")
            if not mid:
                break
            resumes += 1
            print(f"[{task['id']}] --- resume #{resumes} ---", flush=True)
            async with httpx.AsyncClient(timeout=60.0) as client:
                token, _ = await _auth(client, base_url, user, password)
                inference = await _mint_inference(client, base_url, token)
            resp = await sc.resume(
                message_id=str(mid),
                conversation_id=conv_id or "",
                trace_id=trace_id,
                decision="continue",
                note="llm_smoke: continue",
                inference=inference,
                timeout=timeout,
            )
            if "error" in resp:
                error = str(resp["error"])
                break
            result = resp.get("result") or {}
            finish = result.get("finishReason") or result.get("finish_reason")
            print(f"[{task['id']}] resume finish={finish}", flush=True)
    except TimeoutError as e:
        detail = str(e).strip() or "asyncio.wait_for exceeded"
        error = f"timeout: {detail}"
        if turn_started:
            row["notes"].append(
                "startTurn timeout after RPC sent; often hangs after "
                "inference.proxy_spend_enqueued (sidecar stdio/event-pump seam)"
            )
    except Exception as e:
        error = str(e) if str(e).strip() else repr(e)
        print(f"[{task['id']}] ERROR: {e}", file=sys.stderr, flush=True)
    finally:
        elapsed = time.time() - t0
        await sc.close()

    row["elapsed_sec"] = round(elapsed, 1)
    row["finish_reason"] = finish
    row["run_plan"] = _has_run_plan(sc.events)
    # Wire shape: params.event.{type,payload}（probe 顶层 type 常为空）
    unwrapped = [_unwrap_event(e) for e in sc.events]
    row["tool_names"] = [
        (e.get("payload") or {}).get("tool_name")
        for e in unwrapped
        if e.get("type") == "tool_use_start"
    ]
    row["event_types"] = [t for e in unwrapped if (t := e.get("type")) and isinstance(t, str)]
    row["error"] = error
    row["turn_started"] = turn_started

    # 挂起交互：不做硬测强求（仍可跑一眼，但 verdict 归交互类）
    interactive = isinstance(finish, str) and finish.lower() in {
        "ask_user",
        "plan_review",
        "paused",
        "needs_input",
        "suspended",
    }

    checks: list[dict[str, Any]] | None = None
    checks_all_pass = False
    if error is None or interactive:
        try:
            checks = _run_hard_checks(task, workspace, vendor)
            checks_all_pass = all(c["passed"] for c in checks)
            row["checks"] = checks
            row["checks_pass"] = checks_all_pass
            for c in checks:
                mark = "PASS" if c["passed"] else "FAIL"
                print(f"[{task['id']}] check [{mark}] {c['name']}: {c['detail'][:160]}", flush=True)
        except Exception as e:
            row["notes"].append(f"hard_check_error: {e}")
            if error is None:
                error = f"hard_check: {e}"
                row["error"] = error

    if interactive and max_resumes <= 0:
        row["verdict"] = "fail"
        row["fail_class"] = "需决策/交互"
        row["notes"].append("finish=交互类且未 auto-resume（勿死等）")
    elif error is None and checks_all_pass:
        row["verdict"] = "pass"
        row["fail_class"] = None
    else:
        row["verdict"] = "fail"
        row["fail_class"] = _classify_fail(
            error=error,
            finish=finish,
            checks=checks,
            checks_all_pass=checks_all_pass,
            turn_started=turn_started,
            event_count=len(sc.events),
        )

    # 探针产物（无 key）
    artifact = {
        "scenario": f"llm-smoke-{task['id']}",
        "workspace": str(workspace),
        "conversation_id": conv_id,
        "trace_id": trace_id,
        "elapsed_sec": row["elapsed_sec"],
        "finish_reason": finish,
        "tool_names": row["tool_names"],
        "checks": checks,
        "verdict": row["verdict"],
        "fail_class": row["fail_class"],
        "error": error,
        "prompt_preview": prompt[:400],
    }
    art_path = OUT_DIR / f"llm_smoke_{task['id']}_{ts}.json"
    art_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    row["artifact"] = str(art_path.relative_to(_REPO_ROOT)).replace("\\", "/")
    return row


async def main_async(args: argparse.Namespace) -> int:
    stems = [s.strip() for s in args.cards.split(",") if s.strip()]
    card_paths = [_resolve_card(s) for s in stems]
    print(f"cards={[p.name for p in card_paths]} timeout={args.timeout}s", flush=True)

    # 方案层：先探 sidecar 能否起 + inference
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token, user_id = await _auth(client, args.base_url, args.user, args.password)
            inference = await _mint_inference(client, args.base_url, token)
            print(f"preflight auth ok user_id={user_id} model={inference.get('model')}", flush=True)
    except Exception as e:
        report = {
            "generated_at": _utc_now(),
            "path": "D·sidecar",
            "status": "blocked",
            "fail_class": "环境",
            "error": f"preflight auth/inference failed: {e}",
            "rows": [],
            "summary": {"total": 0, "pass": 0, "fail": 0, "blocked": True},
        }
        _write_report(report)
        print(f"BLOCKED: {report['error']}", file=sys.stderr)
        return 2

    # 轻量 sidecar spawn 探活（空工作区目录）
    probe_ws = _WS_ROOT / "_preflight"
    probe_ws.mkdir(parents=True, exist_ok=True)
    (probe_ws / ".keep").write_text("", encoding="utf-8")
    data_dir = OUT_DIR / f"llm_smoke_preflight_{time.strftime('%Y%m%d_%H%M%S')}"
    data_dir.mkdir(parents=True, exist_ok=True)
    sc = SidecarClient(probe_ws, data_dir)
    try:
        await sc.start()
        if sc.proc is None or sc.proc.poll() is not None:
            raise RuntimeError("sidecar exited immediately after spawn")
        init = await sc.initialize(user_id=user_id, inference=inference)
        if "error" in init:
            raise RuntimeError(f"initialize error: {init['error']}")
        print("preflight sidecar initialize OK", flush=True)
    except Exception as e:
        await sc.close()
        report = {
            "generated_at": _utc_now(),
            "path": "D·sidecar",
            "status": "blocked",
            "fail_class": "环境",
            "error": f"sidecar 起不来 / initialize 失败: {e}",
            "rows": [],
            "summary": {"total": 0, "pass": 0, "fail": 0, "blocked": True},
            "env_debt": True,
        }
        _write_report(report)
        print(f"BLOCKED (env debt): {report['error']}", file=sys.stderr)
        return 2
    finally:
        await sc.close()

    rows: list[dict[str, Any]] = []
    for i, path in enumerate(card_paths):
        print(f"\n======== card {i + 1}/{len(card_paths)}: {path.name} ========", flush=True)
        row = await _run_one_card(
            task_path=path,
            base_url=args.base_url,
            user=args.user,
            password=args.password,
            root_id=args.root_id,
            timeout=args.timeout,
            max_resumes=args.max_resumes,
        )
        rows.append(row)
        print(
            f"[{row['task_id']}] verdict={row['verdict']} fail_class={row.get('fail_class')} "
            f"checks_pass={row.get('checks_pass')}",
            flush=True,
        )
        # 首卡若纯环境失败且无 conversation，后续多半同样挂——仍继续记，但标注
        if row.get("fail_class") == "环境" and not row.get("conversation_id") and i == 0:
            print("首卡环境失败；继续尝试余卡以凑证据", flush=True)

    n_pass = sum(1 for r in rows if r.get("verdict") == "pass")
    n_fail = len(rows) - n_pass
    seam_hangs = sum(
        1
        for r in rows
        if r.get("fail_class") == "接缝" and r.get("turn_started") and not r.get("finish_reason")
    )
    report = {
        "generated_at": _utc_now(),
        "path": "D·sidecar",
        "status": "completed",
        "control": "LLM Agent real turn + hard TestExitCode/TestsUnchanged",
        "timeout_sec": args.timeout,
        "max_resumes": args.max_resumes,
        "model_hint": "via /v1/inference/token (platform)",
        "summary": {
            "total": len(rows),
            "pass": n_pass,
            "fail": n_fail,
            "by_fail_class": _count_fail_class(rows),
        },
        "known_limits": {
            "auth_inference": "preflight ok",
            "sidecar_initialize": "preflight ok",
            "hard_checks_reached": n_pass + sum(1 for r in rows if r.get("checks") is not None),
            "post_llm_hang_cards": seam_hangs,
            "seam_note": (
                "startTurn may hang after inference.proxy_spend_enqueued "
                "(message_start only); Windows sidecar stdio/event-pump"
                if seam_hangs
                else None
            ),
        },
        "rows": rows,
        "notes": [
            "首波 Fix 烟感；不进 PR 门禁；禁直绑 vendor 写盘",
            "ask_user 默认 max_resumes=0 → fail_class=需决策/交互",
            "若 startTurn 在 LLM proxy_spend 后无 finish：记 fail_class=接缝（Windows sidecar stdio/event-pump）",
        ],
    }
    out = _write_report(report)
    print(f"\nreport={out} pass={n_pass}/{len(rows)}", flush=True)
    return 0 if n_pass == len(rows) else 1


def _count_fail_class(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        fc = r.get("fail_class")
        if fc:
            out[fc] = out.get(fc, 0) + 1
    return out


def _write_report(report: dict[str, Any]) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORT_DIR / "llm_smoke_latest.json"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamped = _REPORT_DIR / f"llm_smoke_{stamp}.json"
    text = json.dumps(report, ensure_ascii=False, indent=2)
    latest.write_text(text, encoding="utf-8")
    stamped.write_text(text, encoding="utf-8")
    return latest


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cards",
        default=",".join(_DEFAULT_CARD_STEMS),
        help="逗号分隔卡 stem（默认首波 Fix）",
    )
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--user", default=DEFAULT_USERNAME)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    p.add_argument("--root-id", default=AGENTCORE_ROOT_ID)
    p.add_argument("--timeout", type=float, default=450.0, help="单卡 startTurn timeout 秒")
    p.add_argument(
        "--max-resumes",
        type=int,
        default=0,
        help="ask_user/plan_review 自动 resume 次数（烟感默认 0，勿死等）",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
