"""Aggregate product-AI log stats into a structured result."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agentcore.observability.query.jsonl import JsonlLogSource, ReadFilter, ReadStats, iter_events

_EARLY_FINISH_FLAGS = {"length", "max_rounds", "degraded", "unproductive"}
# Convergence-governance events → per-trace tally field. Aligned to what the
# engine actually emits (governance.py / ceiling.py): the hard-ceiling event is
# engine.ceiling_finalize with reason=max_rounds|token_budget — the old
# engine.max_rounds_exhausted name never fires (dead name, removed).
_GOVERNANCE_EVENTS = {
    "engine.loop_nudge": "loop_nudge",
    "engine.loop_finalize": "loop_finalize",
    "engine.ceiling_finalize": "ceiling_finalize",
}
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
_HEX32_RE = re.compile(r"^[0-9a-f]{32}", re.I)
_SIG_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
_SIG_HEX_RE = re.compile(r"\b[0-9a-f]{16,}\b", re.I)
_SIG_ADDR_RE = re.compile(r"0x[0-9a-f]+\b", re.I)
_SIG_NUM_RE = re.compile(r"\b\d+\b")
_SIG_WS_RE = re.compile(r"\s+")


def error_signature(raw: object) -> str:
    """Normalize an error event string for clustering."""
    text = raw if isinstance(raw, str) else str(raw if raw is not None else "?")
    s = _SIG_UUID_RE.sub("<uuid>", text)
    s = _SIG_ADDR_RE.sub("<addr>", s)
    s = _SIG_HEX_RE.sub("<hex>", s)
    s = _SIG_NUM_RE.sub("<n>", s)
    return _SIG_WS_RE.sub(" ", s).strip() or "?"


# 双轨对账 (turn_metrics column ↔ event-recomputed trace field): the runtime
# tallies collab counters in-process (delegate tool accumulator → turn_metrics
# columns AND chat.turn_complete / chat.resume_complete kwargs); log_stats
# recomputes the same four from raw delegate.* events. The map is the semantic
# contract between the two implementations — collab_drift() makes silent
# divergence ring. Event sources per field:
#   boundary_yields ↔ delegate.yielded count
#   scope_signals   ↔ delegate.completed.scope sum
#   revises         ↔ delegate.continuation_ok + delegate.run_redirect_hot
#                     (runtime note_continuation covers BOTH 定向唤回 paths)
#   escalations     ↔ delegate.completed.escalations sum
COLLAB_FIELD_MAP: dict[str, str] = {
    "boundary_yields": "yields",
    "scope_signals": "scope_boundaries",
    "revises": "revise",
    "escalations": "escalations",
}


def new_trace() -> dict[str, Any]:
    return {
        "turn": False,
        "delegated": False,
        "finish_reason": None,
        "contract_retry": 0,
        "contract_failed": 0,
        "revise": 0,
        "revise_failed": 0,
        "delegate_batches": 0,
        "yields": 0,
        "scope_yields": 0,
        "escalations": 0,
        "scope_boundaries": 0,
        "scope_ratio_sum": 0.0,
        "scope_ratio_n": 0,
        "loop_nudge": 0,
        "loop_finalize": 0,
        "ceiling_finalize": 0,
        # Runtime-reported collab counters off chat.turn_complete (None until a
        # carrying line is seen; absent on legacy / resume lines).
        "reported_collab": None,
    }


def accumulate_trace(rec: dict[str, Any], event: str, obj: dict[str, Any]) -> None:
    """Fold one log line into its trace's collaboration-quality tally."""
    if event in ("chat.turn_complete", "chat.resume_complete"):
        rec["turn"] = True
        rec["delegated"] = rec["delegated"] or bool(obj.get("delegated"))
        rec["finish_reason"] = obj.get("finish_reason") or rec["finish_reason"]
        # Runtime authority for the 双轨对账: the closing line carries the same
        # four counters the turn persists to turn_metrics. A paused close is a
        # mid-turn snapshot (pre-resume signals only) — never authoritative; a
        # terminal close overwrites it. Traces whose terminal close carries no
        # counters (legacy / STOP resume) stay 不可对账, not drift.
        if "boundary_yields" in obj and obj.get("finish_reason") != "paused":
            rec["reported_collab"] = {
                col: int(obj.get(col, 0) or 0) for col in COLLAB_FIELD_MAP
            }
    elif event == "contract.retry":
        rec["contract_retry"] += 1
    elif event == "contract.failed":
        rec["contract_failed"] += 1
    # NOTE: revise.started / run.revise_failed were dead names (no emit site).
    # 定向唤回 has TWO live paths, both counted by runtime note_continuation:
    # continue_from (delegate.continuation_ok) and redirect 热修
    # (delegate.run_redirect_hot).
    elif event in ("delegate.continuation_ok", "delegate.run_redirect_hot"):
        rec["revise"] += 1
    elif event == "run.continuation_failed":
        rec["revise_failed"] += 1
    elif event == "delegate.started":
        rec["delegated"] = True
        rec["delegate_batches"] += 1
    elif event == "delegate.completed":
        rec["escalations"] += int(obj.get("escalations", 0) or 0)
        rec["scope_boundaries"] += int(obj.get("scope", 0) or 0)
        if obj.get("escalations"):
            rec["scope_ratio_sum"] += float(obj.get("scope_ratio", 0.0) or 0.0)
            rec["scope_ratio_n"] += 1
    elif event == "delegate.yielded":
        rec["yields"] += 1
        if obj.get("reason") == "scope":
            rec["scope_yields"] += 1
    elif event == "engine.loop_nudge":
        rec["loop_nudge"] += 1
    elif event == "engine.loop_finalize":
        rec["loop_finalize"] += 1
    elif event == "engine.ceiling_finalize":
        rec["ceiling_finalize"] += 1


def classify_worker(agent_id: str) -> tuple[str, str]:
    """Map agent_id → (agg_label, family)."""
    if not agent_id or agent_id == "?":
        return "?", "?"
    if agent_id == "CEO":
        return "CEO", "CEO"
    for prefix, family in (("del_", "del"), ("debate_", "debate"), ("add_", "add")):
        if agent_id.startswith(prefix):
            rest = agent_id[len(prefix) :]
            m = _UUID_RE.match(rest) or _HEX32_RE.match(rest)
            if m and len(rest) > m.end() and rest[m.end()] == "_":
                return f"{family} · {rest[m.end() + 1 :]}", family
            return f"{family} · *", family
    if _UUID_RE.match(agent_id) or _HEX32_RE.match(agent_id):
        return "uuid · *", "uuid"
    return agent_id, "other"


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


@dataclass
class StatsQueryResult:
    """Structured stats payload for human / JSON output."""

    total: int = 0
    bad_lines: int = 0
    excluded_synthetic: int = 0
    synthetic_by_kind: dict[str, int] = field(default_factory=dict)
    window_label: str = ""
    since: str | None = None
    files: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    error_clusters: list[dict[str, Any]] = field(default_factory=list)
    turn_completes: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    round_ends: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    cost_records: list[dict[str, Any]] = field(default_factory=list)
    collaboration: dict[str, Any] = field(default_factory=dict)
    governance: dict[str, Any] = field(default_factory=dict)
    summaries: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def collab_drift(traces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """双轨对账: runtime-reported collab counters vs event-recomputed tallies.

    Compares, per completed turn that carries the runtime counters on
    chat.turn_complete, each ``turn_metrics`` column against the tally
    recomputed from raw delegate.* events (``COLLAB_FIELD_MAP``). A non-empty
    ``by_field`` means one implementation changed semantics without the other —
    the silent-drift failure mode this check exists to catch. Legacy lines
    without the counters are skipped (not drift).
    """
    checked = 0
    by_field: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    for tid, t in traces.items():
        reported = t.get("reported_collab")
        if not t["turn"] or reported is None:
            continue
        checked += 1
        for col, trace_field in COLLAB_FIELD_MAP.items():
            if int(reported.get(col, 0)) != int(t[trace_field]):
                by_field[col] = by_field.get(col, 0) + 1
                if len(samples) < 5:
                    samples.append(
                        {
                            "trace_id": tid,
                            "field": col,
                            "reported": int(reported.get(col, 0)),
                            "recomputed": int(t[trace_field]),
                        }
                    )
    return {"checked_turns": checked, "by_field": by_field, "samples": samples}


def _collab_summary(traces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    turns = [t for t in traces.values() if t["turn"]]
    if not turns:
        return {}
    n = len(turns)
    delegated = [t for t in turns if t["delegated"]]
    nd = len(delegated)
    rework = [
        t
        for t in turns
        if t["contract_retry"] or t["contract_failed"] or t["revise"] or t["revise_failed"]
    ]
    out: dict[str, Any] = {
        "turns": n,
        "delegated_turns": nd,
        "rework_rate": len(rework) / n,
        "rework_turns": len(rework),
        "contract_retry": sum(t["contract_retry"] for t in turns),
        "contract_failed": sum(t["contract_failed"] for t in turns),
        "revise": sum(t["revise"] for t in turns),
    }
    if nd:
        survived = [t for t in delegated if t["yields"] == 0]
        drift = [t for t in delegated if t["scope_yields"] or t["scope_boundaries"]]
        out["first_plan_survive_rate"] = len(survived) / nd
        out["drift_rate"] = len(drift) / nd
    idle = [
        t
        for t in turns
        if t["loop_nudge"]
        or t["loop_finalize"]
        or t["ceiling_finalize"]
        or (t["finish_reason"] or "").lower() in _EARLY_FINISH_FLAGS
    ]
    out["idle_or_early_rate"] = len(idle) / n
    out["loop_nudge"] = sum(t["loop_nudge"] for t in turns)
    out["loop_finalize"] = sum(t["loop_finalize"] for t in turns)
    out["ceiling_finalize"] = sum(t["ceiling_finalize"] for t in turns)
    out["drift"] = collab_drift(traces)
    return out


def _governance_summary(
    events: Counter[str],
    traces: dict[str, dict[str, Any]],
    ceiling_reasons: Counter[str] | None = None,
) -> dict[str, Any]:
    """Governance totals split in-turn vs orphan; ceiling_finalize split by reason.

    ``reason=max_rounds`` on engine.ceiling_finalize carries the old
    「轮预算耗尽」semantics (the retired engine.max_rounds_exhausted name).
    """
    completed = [t for t in traces.values() if t["turn"]]
    out: dict[str, Any] = {}
    for e, field_name in _GOVERNANCE_EVENTS.items():
        c = events.get(e, 0)
        if not c:
            continue
        in_turn = sum(t[field_name] for t in completed)
        entry: dict[str, Any] = {"total": c, "in_turn": in_turn, "orphan": c - in_turn}
        if e == "engine.ceiling_finalize" and ceiling_reasons:
            entry["by_reason"] = dict(ceiling_reasons)
        out[e] = entry
    return out


def compute_stats(
    log_file: Path,
    *,
    since: datetime | None = None,
    include_synthetic: bool = False,
    window_label: str = "",
) -> StatsQueryResult:
    """Scan JSONL (+ backups) and build a :class:`StatsQueryResult`."""
    filt = ReadFilter(since=since, include_synthetic=include_synthetic)
    read_stats = ReadStats()
    events: Counter[str] = Counter()
    errors: list[dict[str, Any]] = []
    turn_completes: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    round_ends: list[dict[str, Any]] = []
    llm_calls: list[dict[str, Any]] = []
    cost_records: list[dict[str, Any]] = []
    traces: dict[str, dict[str, Any]] = {}
    ceiling_reasons: Counter[str] = Counter()

    for obj in iter_events(JsonlLogSource(log_file), filt, stats=read_stats):
        event = obj.get("event", "")
        events[event] += 1
        tid = obj.get("trace_id")
        if tid:
            accumulate_trace(traces.setdefault(str(tid), new_trace()), event, obj)
        if obj.get("level") == "error":
            errors.append(obj)
        if event == "engine.ceiling_finalize":
            ceiling_reasons[str(obj.get("reason") or "?")] += 1
        if event == "chat.turn_complete":
            turn_completes.append(obj)
        elif event == "tool.execute_end":
            tool_calls.append(obj)
        elif event == "react.round_end":
            round_ends.append(obj)
        elif event == "llm.call":
            llm_calls.append(obj)
        elif event == "cost.recorded":
            cost_records.append(obj)

    clusters: dict[str, dict[str, Any]] = {}
    for e in errors:
        raw = e.get("event", "?")
        sig = error_signature(raw)
        bucket = clusters.get(sig)
        if bucket is None:
            sample = raw if isinstance(raw, str) else str(raw if raw is not None else "?")
            clusters[sig] = {"signature": sig, "count": 1, "sample": sample}
        else:
            bucket["count"] = int(bucket["count"]) + 1
    error_clusters = sorted(clusters.values(), key=lambda x: -int(x["count"]))[:15]

    summaries: dict[str, Any] = {}
    if turn_completes:
        durations = [t["duration_ms"] for t in turn_completes if t.get("duration_ms")]
        rounds = [t["rounds"] for t in turn_completes if t.get("rounds")]
        summaries["turns"] = {
            "count": len(turn_completes),
            "duration_avg_ms": _avg(durations) if durations else None,
            "duration_min_ms": min(durations) if durations else None,
            "duration_max_ms": max(durations) if durations else None,
            "rounds_avg": _avg(rounds) if rounds else None,
            "delegated": sum(1 for t in turn_completes if t.get("delegated")),
            "input_tokens_avg": _avg([t.get("input_tokens", 0) for t in turn_completes]),
            "output_tokens_avg": _avg([t.get("output_tokens", 0) for t in turn_completes]),
        }
    if llm_calls:
        timed = [c for c in llm_calls if c.get("latency_ms")]
        summaries["llm"] = {
            "count": len(llm_calls),
            "timed": len(timed),
            "latency_avg_ms": _avg([c["latency_ms"] for c in timed]) if timed else None,
            "finish_reason": dict(Counter(c.get("finish_reason", "?") for c in llm_calls)),
        }
    if tool_calls:
        errs = sum(1 for t in tool_calls if t.get("status") not in ("ok", None))
        summaries["tools"] = {
            "count": len(tool_calls),
            "failed": errs,
            "success_rate": (len(tool_calls) - errs) / len(tool_calls) if tool_calls else 0.0,
            "by_tool": dict(Counter(t.get("tool", "?") for t in tool_calls)),
        }
    if cost_records:
        total_nano = sum(int(c.get("total_nano", 0) or 0) for c in cost_records)
        by_role: Counter[str] = Counter()
        for c in cost_records:
            role_map = c.get("by_role") or {}
            if isinstance(role_map, dict):
                for role, bucket in role_map.items():
                    if isinstance(bucket, dict):
                        by_role[str(role)] += int(bucket.get("total_nano", 0) or 0)
        summaries["cost"] = {
            "turns": len(cost_records),
            "total_nano": total_nano,
            "total_usd": total_nano / 1e9,
            "by_role_nano": dict(by_role),
        }

    return StatsQueryResult(
        total=read_stats.total_kept,
        bad_lines=read_stats.bad_lines,
        excluded_synthetic=read_stats.excluded_synthetic,
        synthetic_by_kind=dict(read_stats.synthetic_by_kind),
        window_label=window_label,
        since=since.strftime("%Y-%m-%dT%H:%M:%SZ") if since else None,
        files=[str(p) for p in read_stats.files],
        event_counts=dict(events.most_common()),
        errors=errors,
        error_clusters=error_clusters,
        turn_completes=turn_completes,
        tool_calls=tool_calls,
        round_ends=round_ends,
        llm_calls=llm_calls,
        cost_records=cost_records,
        collaboration=_collab_summary(traces),
        governance=_governance_summary(events, traces, ceiling_reasons),
        summaries=summaries,
    )


# Re-export names used by human printers / legacy tests.
GOVERNANCE_EVENTS = _GOVERNANCE_EVENTS
EARLY_FINISH_FLAGS = _EARLY_FINISH_FLAGS
WORKER_ROW_BUDGET = 40
UUID_RE = _UUID_RE
HEX32_RE = _HEX32_RE
SIG_WS_RE = _SIG_WS_RE
