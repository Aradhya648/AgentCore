"""Scan logger.* call sites and regenerate agentcore/observability/catalog.py.

Also pair with ``gen_log_event_docs.py`` to refresh the markdown event table::

    uv run python scripts/sync_log_event_registry.py
    uv run python scripts/gen_log_event_docs.py
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTCORE = ROOT / "agentcore"
OUT = AGENTCORE / "observability" / "catalog.py"
LEVELS = {"info", "warning", "error", "debug", "exception", "critical"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")

# Lightweight field schemas for high-value events (docs / debugging).
KEY_FIELDS: dict[str, dict[str, str]] = {
    "chat.turn_start": {
        "preview": "str",
        "chars": "int",
        "history": "int",
        "location": "str",
    },
    "chat.turn_complete": {
        "finish_reason": "str",
        "rounds": "int",
        "input_tokens": "int",
        "output_tokens": "int",
        "reply_preview": "str",
        "delegated": "bool",
        "workers": "int",
        "duration_ms": "int",
        "boundary_yields": "int",
        "scope_signals": "int",
        "revises": "int",
        "escalations": "int",
    },
    "chat.resume_complete": {
        "finish_reason": "str",
        "delegated": "bool",
        "duration_ms": "int",
        "boundary_yields": "int",
        "scope_signals": "int",
        "revises": "int",
        "escalations": "int",
    },
    "delegate.started": {
        "nodes": "int",
        "call": "str",
        "parallel": "int",
        "agents": "list",
        "plan": "list",
        "waves": "list",
    },
    "delegate.completed": {
        "escalations": "int",
        "scope": "int",
        "scope_ratio": "float",
    },
    "delegate.yielded": {"reason": "str"},
    "delegate.continuation_ok": {"run_id": "str"},
    "delegate.continuation_rejected": {"run_id": "str", "reason": "str"},
    "delegate.run_redirect_hot": {
        "execution_id": "str",
        "cancelled_run_id": "str",
        "continuation_run_id": "str",
        "recall_count": "int",
    },
    "worker.escalate": {
        "kind": "str",
        "blocking": "bool",
        "question": "str",
        "assumption": "str",
    },
    "tool.execute_start": {"tool": "str"},
    "tool.execute_end": {
        "tool": "str",
        "status": "str",
        "duration_ms": "int",
        "reason": "str",
    },
    "tool.args_parse_failed": {"pos": "int", "msg": "str", "args_preview": "str"},
    "tool.web_search": {"query": "str", "hosts": "list"},
    "worker.handoff": {
        "run_id": "str",
        "has_summary": "bool",
        "chars": "int",
        "body_chars": "int",
        "has_motion_card": "bool",
    },
    "react.round_start": {"round": "int"},
    "react.round_end": {
        "round": "int",
        "tools": "int",
        "input_tokens": "int",
        "output_tokens": "int",
        "reasoning_tokens": "int",
        "done": "bool",
    },
    "engine.loop_nudge": {},
    "engine.loop_finalize": {},
    "engine.ceiling_finalize": {
        "reason": "str",
        "thrashing": "bool",
        "rounds": "int",
        "tokens": "int",
        "token_budget": "int",
    },
    "llm.call": {
        "scenario": "str",
        "model": "str",
        "latency_ms": "int",
        "finish_reason": "str",
        "input_tokens": "int",
        "output_tokens": "int",
        "reasoning_tokens": "int",
        "stream": "bool",
        "cost_nano": "int",
    },
    "llm.request": {"scenario": "str", "model": "str"},
    "llm.response": {"scenario": "str", "model": "str"},
    "llm.call_failed": {"error": "str", "scenario": "str"},
    "contract.retry": {},
    "contract.failed": {},
    "run.failed": {"error": "str"},
    "run.captain_failed": {"error": "str"},
    "cost.recorded": {
        "runs": "int",
        "total_nano": "int",
        "total_usd": "float",
        "models": "list",
        "by_role": "dict",
    },
    "cost.ledger_write_failed": {"error": "str"},
    "cost.ledger_drain_before_reconcile_failed": {},
    "workspace.snapshot_created": {},
    "workspace.snapshot_failed": {"error": "str"},
    "pipeline.error": {"error": "str"},
    "http.unhandled_error": {"method": "str", "path": "str", "error": "str"},
    "approval.sandbox_auto_pass": {"tool": "str"},
    "approval.timeout": {"tool": "str"},
    "firehose.backpressure_drop": {},
}

KEY_DESC: dict[str, str] = {
    "chat.turn_start": "回合起点（preview/chars/history）",
    "chat.turn_complete": "回合收尾（finish_reason/rounds/tokens/delegated）",
    "chat.resume_complete": "暂停恢复回合收尾（终态带协作计数；STOP 终结不带）",
    "delegate.started": "编排委派开始（agents/plan/waves）",
    "delegate.completed": "委派批次完成（escalations/scope）",
    "delegate.yielded": "委派中途让出（replan 边界）",
    "delegate.run_redirect_hot": "redirect 热修续派（revise 重算桶，与 continuation_ok 同义）",
    "worker.escalate": "worker 升级求决策",
    "tool.execute_end": "工具执行结束（status/duration_ms；error 时带 reason）",
    "worker.handoff": "worker 交接（chars=summary 长；body_chars=交付正文长）",
    "react.round_end": "ReAct 轮结束（reasoning_tokens/tools）",
    "engine.loop_nudge": "收敛治理：循环提醒",
    "engine.loop_finalize": "收敛治理：强制收尾",
    "engine.ceiling_finalize": "收敛治理：硬顶强制收尾（reason=max_rounds 轮预算耗尽 / token_budget）",
    "llm.call": "单次 LLM 调用（latency/tokens/cost_nano）",
    "llm.request": "LLM prompt 截断脱敏（需 LOG_LLM_BODIES）",
    "llm.response": "LLM 回复截断脱敏（需 LOG_LLM_BODIES）",
    "cost.recorded": "回合落账成功（含 by_role 角色拆解）",
    "pipeline.error": "回合管线未捕获异常",
    "http.unhandled_error": "HTTP 层未捕获异常",
}


def scan_events() -> set[str]:
    events: set[str] = set()
    for path in AGENTCORE.rglob("*.py"):
        if "observability" in path.parts and path.name in {"catalog.py", "events.py"}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in LEVELS:
                continue
            if not node.args:
                continue
            arg0 = node.args[0]
            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                name = arg0.value
                if NAME_RE.fullmatch(name):
                    events.add(name)
    return events


def _format_spec(name: str) -> list[str]:
    """Emit one EventSpec as one or more lines (keep ≤100 cols)."""
    desc = KEY_DESC.get(name, "")
    fields = KEY_FIELDS.get(name, {})
    if not fields and not desc:
        return [f"    EventSpec(name={name!r}),"]
    if not fields:
        return [f"    EventSpec(name={name!r}, description={desc!r}),"]
    out = [
        "    EventSpec(",
        f"        name={name!r},",
        f"        description={desc!r},",
        "        fields={",
    ]
    for k, v in sorted(fields.items()):
        out.append(f"            {k!r}: FieldType({v!r}),")
    out.append("        },")
    out.append("    ),")
    return out


def write_catalog(events: list[str]) -> None:
    lines = [
        '"""Auto-maintained event catalog for product AI logs.',
        "",
        "Source of truth for event *names* currently emitted via ``logger.*``.",
        "Regenerate with::",
        "",
        "    uv run python scripts/sync_log_event_registry.py",
        "",
        "Do not hand-edit the ``EVENTS`` list — add field/description enrichments",
        "via ``KEY_FIELDS`` / ``KEY_DESC`` in the sync script, then re-run.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from agentcore.observability.events import EventSpec, FieldType",
        "",
        "# fields empty means name-only registration.",
        "EVENTS: list[EventSpec] = [",
    ]
    for name in events:
        lines.extend(_format_spec(name))
    lines.append("]")
    lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    events = sorted(scan_events())
    # Guard against dead names lingering in the enrichment maps (an event name
    # with no emit site never enters the catalog, so its enrichment is a zombie).
    dead = sorted((set(KEY_FIELDS) | set(KEY_DESC)) - set(events))
    for name in dead:
        print(f"WARNING: enrichment for {name!r} has no emit site (dead name?)")
    write_catalog(events)
    print(f"wrote {OUT} ({len(events)} events)")
    if dead:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
