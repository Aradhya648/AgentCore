"""Quick stats from logs/dev.jsonl — event counts, errors, turn quality metrics.

Thin CLI over ``agentcore.observability.query``. Run from apps/server:

    uv run python scripts/log_stats.py                  # last 7 days (default)
    uv run python scripts/log_stats.py --since 24h
    uv run python scripts/log_stats.py --all
    uv run python scripts/log_stats.py --json           # structured (Cursor AI)
    uv run python scripts/log_stats.py --file ../../logs/prod-export/events.jsonl

Reads the repo-root ``logs/dev.jsonl`` by default (plus rotating backups).
Default excludes synthetic ``traffic=eval|test``; use ``--include-synthetic``.
See .cursor/rules/conversation-logs.mdc.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# scripts/ -> server (agentcore importable)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentcore.observability.query.jsonl import (  # noqa: E402
    JsonlLogSource,
    ReadFilter,
    ReadStats,
    discover_log_files,
    iter_events,
)
from agentcore.observability.query.stats import (  # noqa: E402
    GOVERNANCE_EVENTS,
    SIG_WS_RE,
    WORKER_ROW_BUDGET,
    accumulate_trace,
    classify_worker,
    collab_drift,
    compute_stats,
    error_signature,
    new_trace,
)
from agentcore.observability.query.timeutil import parse_since, parse_timestamp  # noqa: E402

# scripts/ -> server -> apps -> <repo root>
LOG_FILE = Path(__file__).resolve().parents[3] / "logs" / "dev.jsonl"

_DEFAULT_SINCE = "7d"
_WORKER_ROW_BUDGET = WORKER_ROW_BUDGET
_GOVERNANCE_EVENTS = GOVERNANCE_EVENTS

# Backward-compatible aliases for tests/test_log_stats.py
_new_trace = new_trace
_accumulate_trace = accumulate_trace
_error_signature = error_signature
_classify_worker = classify_worker
_discover_log_files = discover_log_files
_parse_since = parse_since
_parse_timestamp = parse_timestamp
_SIG_WS_RE = SIG_WS_RE


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _short_agent(agent_id: str, width: int = 28) -> str:
    if len(agent_id) <= width:
        return agent_id
    return agent_id[: width - 1] + "…"


def _print_by_worker(tool_calls: list[dict]) -> None:
    """Aggregate By worker to ≤40 rows: family·role + top anomalous instances."""
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for t in tool_calls:
        by_agent[t.get("agent_id") or "?"].append(t)
    if len(by_agent) <= 1:
        return

    by_label: dict[str, list[dict]] = defaultdict(list)
    agents_per_label: dict[str, set[str]] = defaultdict(set)
    family_of: dict[str, str] = {}
    for agent_id, calls in by_agent.items():
        label, family = classify_worker(agent_id)
        by_label[label].extend(calls)
        agents_per_label[label].add(agent_id)
        family_of[label] = family

    def _row_stats(calls: list[dict]) -> tuple[float, float, str, str]:
        errs = sum(1 for t in calls if t.get("status") not in ("ok", None))
        durs = [t["duration_ms"] for t in calls if t.get("duration_ms")]
        ok_pct = (len(calls) - errs) / len(calls) * 100 if calls else 0.0
        avg_ms = _avg(durs) if durs else 0.0
        top = Counter(t.get("tool", "?") for t in calls).most_common(2)
        tools = ",".join(n for n, _ in top)
        return ok_pct, avg_ms, tools, f"{errs}err" if errs else "ok"

    print("  By worker (family · role):")
    rows = sorted(by_label.items(), key=lambda kv: -len(kv[1]))
    for i, (label, calls) in enumerate(rows):
        if i >= _WORKER_ROW_BUDGET:
            print(f"    … +{len(rows) - i} more families (use --json for full)")
            break
        ok_pct, avg_ms, tools, rest = _row_stats(calls)
        n_agents = len(agents_per_label[label])
        meta = f"×{n_agents}" if n_agents > 1 else ""
        print(
            f"    {label:<28} {meta:<3} {len(calls):>4} calls  "
            f"{ok_pct:5.1f}% ok  avg {avg_ms:.0f}ms  [{tools}]  {rest}"
        )


def _print_convergence_governance(
    events: Counter[str],
    traces: dict[str, dict],
    ceiling_reasons: Counter[str] | None = None,
) -> None:
    present = {e: events.get(e, 0) for e in _GOVERNANCE_EVENTS if events.get(e)}
    if not present:
        return
    completed = [t for t in traces.values() if t["turn"]]
    print("\n── Convergence Governance ──")
    for e, c in sorted(present.items(), key=lambda x: -x[1]):
        in_turn = sum(t[_GOVERNANCE_EVENTS[e]] for t in completed)
        orphan = c - in_turn
        note = f"  ({in_turn} in turns, {orphan} orphan)" if orphan else ""
        # reason=max_rounds is the old「轮预算耗尽」signal; token_budget = token 硬顶.
        if e == "engine.ceiling_finalize" and ceiling_reasons:
            reasons = "  ".join(f"{r}×{n}" for r, n in ceiling_reasons.most_common())
            note += f"  [by reason: {reasons}]"
        print(f"  {c:>4}x  {e}{note}")


def _print_collaboration_quality(traces: dict[str, dict]) -> None:
    from agentcore.observability.query.stats import EARLY_FINISH_FLAGS

    turns = [t for t in traces.values() if t["turn"]]
    if not turns:
        return
    n = len(turns)
    delegated = [t for t in turns if t["delegated"]]
    nd = len(delegated)

    print("\n── Collaboration Quality (协作质量 · MAST) ──")
    print(f"  Turns {n}  (delegated {nd})")

    rework = [
        t
        for t in turns
        if t["contract_retry"] or t["contract_failed"] or t["revise"] or t["revise_failed"]
    ]
    cr = sum(t["contract_retry"] for t in turns)
    cf = sum(t["contract_failed"] for t in turns)
    rv = sum(t["revise"] for t in turns)
    print(
        f"  [验证] 返工率       {len(rework) / n * 100:5.1f}%  "
        f"({len(rework)}/{n} turns; contract-retry {cr}, revise {rv}, contract-failed {cf})"
    )

    if nd:
        survived = [t for t in delegated if t["yields"] == 0]
        replanned = nd - len(survived)
        print(
            f"  [规格] 首计划存活率 {len(survived) / nd * 100:5.1f}%  "
            f"({len(survived)}/{nd} delegated turns ran first plan clean; "
            f"{replanned} needed mid-course replan)"
        )
        drift = [t for t in delegated if t["scope_yields"] or t["scope_boundaries"]]
        ratios = [
            t["scope_ratio_sum"] / t["scope_ratio_n"] for t in delegated if t["scope_ratio_n"]
        ]
        ratio_note = f"; avg scope_ratio {_avg(ratios):.2f}" if ratios else ""
        print(
            f"  [错位] 漂移率       {len(drift) / nd * 100:5.1f}%  "
            f"({len(drift)}/{nd} delegated turns w/ scope signal{ratio_note})"
        )
    else:
        print("  [规格] 首计划存活率    —    (no delegated turns)")
        print("  [错位] 漂移率         —    (no delegated turns)")

    idle = [
        t
        for t in turns
        if t["loop_nudge"]
        or t["loop_finalize"]
        or t["ceiling_finalize"]
        or (t["finish_reason"] or "").lower() in EARLY_FINISH_FLAGS
    ]
    ln = sum(t["loop_nudge"] for t in turns)
    lf = sum(t["loop_finalize"] for t in turns)
    cf_ceiling = sum(t["ceiling_finalize"] for t in turns)
    flags = Counter(
        (t["finish_reason"] or "?")
        for t in turns
        if (t["finish_reason"] or "").lower() in EARLY_FINISH_FLAGS
    )
    flag_note = f"; finish-flags {dict(flags)}" if flags else ""
    print(
        f"  [终止] 空转·早收     {len(idle) / n * 100:5.1f}%  "
        f"({len(idle)}/{n} turns; loop_nudge {ln}, loop_finalize {lf}, "
        f"ceiling_finalize {cf_ceiling}{flag_note})"
    )

    # 双轨对账: runtime turn_metrics counters vs event-recomputed tallies. A hit
    # means one side's semantics moved without the other — surface loudly.
    drift = collab_drift(traces)
    if drift["by_field"]:
        fields = "  ".join(f"{k}×{v}" for k, v in sorted(drift["by_field"].items()))
        print(
            f"  ⚠ 双轨漂移          {fields}  "
            f"(checked {drift['checked_turns']} turns; runtime turn_metrics vs 事件重算不一致)"
        )
        for s in drift["samples"]:
            print(
                f"      trace {s['trace_id'][:12]}…  {s['field']}: "
                f"runtime={s['reported']} recomputed={s['recomputed']}"
            )


def _parse_cli(argv: list[str]) -> tuple[Path, datetime | None, str | None, bool, bool]:
    """Return (log_file, since_cutoff, window_label, include_synthetic, as_json)."""
    log_file = LOG_FILE
    since_spec: str | None = _DEFAULT_SINCE
    window_label = f"last {_DEFAULT_SINCE}"
    include_synthetic = False
    as_json = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--file" and i + 1 < len(argv):
            log_file = Path(argv[i + 1])
            i += 2
        elif arg == "--since" and i + 1 < len(argv):
            since_spec = argv[i + 1]
            window_label = f"--since {since_spec}"
            i += 2
        elif arg == "--all":
            since_spec = None
            window_label = "--all"
            i += 1
        elif arg == "--include-synthetic":
            include_synthetic = True
            i += 1
        elif arg == "--json":
            as_json = True
            i += 1
        elif arg in ("-h", "--help"):
            print(__doc__)
            raise SystemExit(0)
        else:
            print(f"Unknown argument: {arg}", file=sys.stderr)
            raise SystemExit(2)
    try:
        cutoff = parse_since(since_spec) if since_spec else None
    except ValueError as e:
        raise SystemExit(str(e)) from e
    return log_file, cutoff, window_label, include_synthetic, as_json


def _print_human(
    *,
    log_file: Path,
    since_cutoff: datetime | None,
    window_label: str,
    include_synthetic: bool,
) -> None:
    files = discover_log_files(log_file)
    if not files:
        print(f"Log file not found: {log_file}")
        print("Set LOG_FILE=logs/dev.jsonl in apps/server/.env and run a turn first.")
        sys.exit(1)

    events: Counter[str] = Counter()
    errors: list[dict] = []
    turn_completes: list[dict] = []
    tool_calls: list[dict] = []
    round_ends: list[dict] = []
    llm_calls: list[dict] = []
    cost_records: list[dict] = []
    traces: dict[str, dict] = {}
    ceiling_reasons: Counter[str] = Counter()
    read_stats = ReadStats()
    filt = ReadFilter(since=since_cutoff, include_synthetic=include_synthetic)

    for obj in iter_events(JsonlLogSource(log_file), filt, stats=read_stats):
        event = obj.get("event", "")
        events[event] += 1
        tid = obj.get("trace_id")
        if tid:
            accumulate_trace(traces.setdefault(tid, new_trace()), event, obj)
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

    total = read_stats.total_kept
    bad_lines = read_stats.bad_lines
    excluded_synthetic = read_stats.excluded_synthetic
    synthetic_by_kind = Counter(read_stats.synthetic_by_kind)

    print(f"\n{'=' * 60}")
    print(f"  Log Stats  |  {total:,} events  |  {bad_lines} bad lines")
    if since_cutoff is not None:
        print(
            f"  Window: since {since_cutoff.strftime('%Y-%m-%dT%H:%M:%SZ')}  ({window_label})"
        )
    else:
        print(f"  Window: all time  ({window_label})")
    if len(files) > 1:
        print(f"  Files: {files[-1].name} + {len(files) - 1} rotation backup(s)")
    else:
        print(f"  File: {files[0] if files else log_file}")
    if excluded_synthetic:
        parts = " / ".join(f"{k} {synthetic_by_kind[k]}" for k in sorted(synthetic_by_kind))
        print(f"  excluded {excluded_synthetic} synthetic lines ({parts})")
    elif not include_synthetic:
        print("  excluded 0 synthetic lines (eval / test)")
    print(f"{'=' * 60}\n")

    if total == 0:
        print("  (no events in window)")
        print()
        return

    print("── Event Distribution (top 25) ──")
    for event, count in events.most_common(25):
        pct = count / total * 100 if total else 0
        bar = "█" * int(pct / 2)
        print(f"  {count:>6}  {pct:5.1f}%  {bar:<25} {event}")

    if errors:
        print(f"\n── Errors ({len(errors)} total) ──")
        clusters: dict[str, dict[str, object]] = {}
        for e in errors:
            raw = e.get("event", "?")
            sig = error_signature(raw)
            bucket = clusters.get(sig)
            if bucket is None:
                sample = raw if isinstance(raw, str) else str(raw if raw is not None else "?")
                clusters[sig] = {"count": 1, "sample": sample}
            else:
                bucket["count"] = int(bucket["count"]) + 1
        for sig, info in sorted(clusters.items(), key=lambda kv: -int(kv[1]["count"]))[:15]:
            count = int(info["count"])
            sample = str(info["sample"])
            display = sig if len(sig) <= 100 else sig[:97] + "…"
            print(f"  {count:>4}x  {display}")
            if sample != sig:
                sample_flat = SIG_WS_RE.sub(" ", sample).strip()
                if len(sample_flat) > 120:
                    sample_flat = sample_flat[:117] + "…"
                print(f"         e.g. {sample_flat}")

    if turn_completes:
        print(f"\n── Turns (chat.turn_complete: {len(turn_completes)}) ──")
        durations = [t["duration_ms"] for t in turn_completes if t.get("duration_ms")]
        rounds = [t["rounds"] for t in turn_completes if t.get("rounds")]
        in_tok = [t.get("input_tokens", 0) for t in turn_completes]
        out_tok = [t.get("output_tokens", 0) for t in turn_completes]
        delegated = sum(1 for t in turn_completes if t.get("delegated"))
        if durations:
            print(
                f"  Duration   avg={_avg(durations):.0f}ms  min={min(durations)}  max={max(durations)}"
            )
        # Phase-0 latency (AI 延迟观测): prepare/assemble wall-clock + captain TTFT.
        # Nulls omitted (missing path ≠ 0). Not the same as llm.call latency_ms.
        prepare_vals = [t["prepare_ms"] for t in turn_completes if t.get("prepare_ms") is not None]
        assemble_vals = [t["assemble_ms"] for t in turn_completes if t.get("assemble_ms") is not None]
        ttft_r = [
            t["ttft_reasoning_ms"] for t in turn_completes if t.get("ttft_reasoning_ms") is not None
        ]
        ttft_c = [
            t["ttft_content_ms"] for t in turn_completes if t.get("ttft_content_ms") is not None
        ]
        if prepare_vals or assemble_vals or ttft_r or ttft_c:
            parts: list[str] = []
            if prepare_vals:
                parts.append(f"prepare avg={_avg(prepare_vals):.0f}ms")
            if assemble_vals:
                parts.append(f"assemble avg={_avg(assemble_vals):.0f}ms")
            if ttft_r:
                parts.append(f"ttft_reasoning avg={_avg(ttft_r):.0f}ms")
            if ttft_c:
                parts.append(f"ttft_content avg={_avg(ttft_c):.0f}ms")
            print(f"  Phase-0    {'  '.join(parts)}")
        if rounds:
            print(f"  Rounds     avg={_avg(rounds):.1f}  min={min(rounds)}  max={max(rounds)}")
        print(f"  Tokens     in avg={_avg(in_tok):.0f}  out avg={_avg(out_tok):.0f}")
        print(f"  Delegated  {delegated}/{len(turn_completes)} turns spun up a team")

    if round_ends:
        print(f"\n── ReAct Rounds (react.round_end: {len(round_ends)}) ──")
        tools_per = [r.get("tools", 0) for r in round_ends]
        rtok = [r.get("reasoning_tokens", 0) for r in round_ends]
        otok = [r.get("output_tokens", 0) for r in round_ends]
        spinning = sum(1 for n in tools_per if n >= 3)
        print(
            f"  Tools/round    avg={_avg(tools_per):.1f}  max={max(tools_per)}  ({spinning} rounds ≥3 tools)"
        )
        print(
            f"  Reasoning tok  avg={_avg(rtok):.0f}/round   Output tok avg={_avg(otok):.0f}/round"
        )

    if llm_calls:
        print(f"\n── LLM Calls (llm.call: {len(llm_calls)}) ──")
        timed = [c for c in llm_calls if c.get("latency_ms")]
        stubbed = len(llm_calls) - len(timed)
        lat = [c["latency_ms"] for c in timed]
        in_tok = [c.get("input_tokens", 0) for c in llm_calls]
        out_tok = [c.get("output_tokens", 0) for c in llm_calls]
        rea_tok = [c.get("reasoning_tokens", 0) for c in llm_calls]
        in_sum = sum(in_tok)
        hit_sum = sum(c.get("cache_hit_tokens", 0) for c in llm_calls)
        if lat:
            print(f"  Latency    avg={_avg(lat):.0f}ms  max={max(lat)}ms")
        print(
            f"  Tokens     in avg={_avg(in_tok):.0f}  out avg={_avg(out_tok):.0f}"
            f"  reasoning avg={_avg(rea_tok):.0f}"
        )
        if in_sum:
            print(f"  Cache      {hit_sum / in_sum * 100:.1f}% of input tokens hit cache")
        fr = Counter(c.get("finish_reason", "?") for c in llm_calls)
        print(f"  Finish     {'  '.join(f'{k}×{v}' for k, v in fr.most_common())}")
        if stubbed:
            print(
                f"  (excluded {stubbed} llm.call without latency_ms from By scenario · model — likely test stubs)"
            )
        by_sm: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for c in timed:
            by_sm[(c.get("scenario", "?"), c.get("model", "?"))].append(c)
        if by_sm:
            print("  By scenario · model:")
            for (scenario, model), calls in sorted(by_sm.items(), key=lambda kv: -len(kv[1])):
                c_lat = [x["latency_ms"] for x in calls]
                dur = f"avg {_avg(c_lat):.0f}ms"
                c_in = _avg([x.get("input_tokens", 0) for x in calls])
                c_out = _avg([x.get("output_tokens", 0) for x in calls])
                label = f"{scenario} · {model}"
                print(
                    f"    {label:<34} {len(calls):>3} calls  {dur:<11} in {c_in:.0f} out {c_out:.0f}"
                )
        priced = [c for c in llm_calls if "cost_nano" in c]
        print(f"  Cost       {len(priced)}/{len(llm_calls)} calls carry cost")
        if priced:
            by_spend: dict[tuple[str, str], list[dict]] = defaultdict(list)
            for c in priced:
                by_spend[(c.get("scenario", "?"), c.get("model", "?"))].append(c)
            total_nano = sum(int(c.get("cost_nano") or 0) for c in priced)
            print(f"  Spend      ¥{total_nano / 1e9:.6f}  ({total_nano:,} nano-CNY)")
            print("  By scenario · model spend:")
            for (scenario, model), calls in sorted(
                by_spend.items(),
                key=lambda kv: -sum(int(x.get("cost_nano") or 0) for x in kv[1]),
            ):
                nano = sum(int(x.get("cost_nano") or 0) for x in calls)
                label = f"{scenario} · {model}"
                print(
                    f"    {label:<34} {len(calls):>3} calls  ¥{nano / 1e9:.6f}"
                    f"  ({nano:,} nano)"
                )

    if tool_calls:
        print(f"\n── Tool Calls ({len(tool_calls)} total) ──")
        names = Counter(t.get("tool", "?") for t in tool_calls)
        errs = sum(1 for t in tool_calls if t.get("status") not in ("ok", None))
        durs = [t["duration_ms"] for t in tool_calls if t.get("duration_ms")]
        print(
            f"  Success rate: {(len(tool_calls) - errs) / len(tool_calls) * 100:.1f}%  ({errs} failed)"
        )
        if durs:
            print(f"  Duration   avg={_avg(durs):.0f}ms  max={max(durs)}ms")
        for name, c in names.most_common(15):
            ne = sum(
                1
                for t in tool_calls
                if t.get("tool") == name and t.get("status") not in ("ok", None)
            )
            print(f"    {c:>4}x  {name}{f'  ({ne} err)' if ne else ''}")

        _print_by_worker(tool_calls)

    if cost_records:
        print(f"\n── Cost (cost.recorded: {len(cost_records)} turns) ──")
        total_nano = sum(int(c.get("total_nano", 0) or 0) for c in cost_records)
        total_yuan = total_nano / 1e9
        print(f"  Total      ¥{total_yuan:.6f}  ({total_nano:,} nano-CNY)")
        print(f"  Per turn   avg ¥{total_yuan / len(cost_records):.6f}")
        model_mix: Counter[str] = Counter()
        role_nano: Counter[str] = Counter()
        role_runs: Counter[str] = Counter()
        for c in cost_records:
            for m in c.get("models") or []:
                model_mix[m] += 1
            by_role = c.get("by_role") or {}
            if isinstance(by_role, dict):
                for role, bucket in by_role.items():
                    if not isinstance(bucket, dict):
                        continue
                    role_nano[str(role)] += int(bucket.get("total_nano", 0) or 0)
                    role_runs[str(role)] += int(bucket.get("runs", 0) or 0)
        if model_mix:
            print(f"  Models     {'  '.join(f'{m}×{n}' for m, n in model_mix.most_common())}")
        if role_nano:
            parts = [
                f"{role} ${role_nano[role] / 1e9:.4f} ({role_runs[role]} runs)"
                for role, _ in role_nano.most_common()
            ]
            print(f"  By role    {'  '.join(parts)}")

    _print_convergence_governance(events, traces, ceiling_reasons)
    _print_collaboration_quality(traces)
    print()


def main() -> None:
    log_file, since_cutoff, window_label, include_synthetic, as_json = _parse_cli(
        sys.argv[1:]
    )
    if as_json:
        if not discover_log_files(log_file):
            print(
                json.dumps(
                    {"error": "log_file_not_found", "path": str(log_file)},
                    ensure_ascii=False,
                )
            )
            sys.exit(1)
        result = compute_stats(
            log_file,
            since=since_cutoff,
            include_synthetic=include_synthetic,
            window_label=window_label or "",
        )
        print(json.dumps(result.to_json_dict(), ensure_ascii=False, default=str))
        return
    _print_human(
        log_file=log_file,
        since_cutoff=since_cutoff,
        window_label=window_label or "",
        include_synthetic=include_synthetic,
    )


if __name__ == "__main__":
    main()
