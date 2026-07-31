"""Decision spine — compact decision-level evidence for one ``trace_id``.

Product surface for product-AI logs (飞行记录仪证据面). Distinct from
``turn_spine`` (``load_conversation_spine_events`` / ``spine_events`` = session
``chat.turn_start|complete`` directory).

Summary truth = persisted ``turn_metrics`` (or export ``turn_metrics.jsonl``).
Cost truth = ``cost_events`` by ``trace_id`` (turn_metrics has no cost columns).
Drift L1 = JSONL-internal ``collab_drift``; Drift L2 = turn_metrics ⋈ JSONL
close/recompute — never silently pick one side.
"""

from __future__ import annotations

from typing import Any

from agentcore.observability.query.stats import (
    COLLAB_FIELD_MAP,
    accumulate_trace,
    collab_drift,
    new_trace,
)

SCHEMA_VERSION = "decision_spine.v0"

# Key decision / failure events that belong on the spine (not the firehose).
_DECISION_EVENTS = frozenset(
    {
        "delegate.started",
        "delegate.completed",
        "delegate.yielded",
        "delegate.acceptance_resolved",
        "delegate.completion_criteria_unmet",
        "delegate.continuation_ok",
        "delegate.continuation_rejected",
        "delegate.run_redirect_hot",
        "worker.escalate",
        "worker.handoff",
        "engine.ceiling_finalize",
        "engine.loop_finalize",
        "run.failed",
        "run.captain_failed",
        "pipeline.error",
        "approval.timeout",
        # Local solo cancel has no coordination.user_stop_* — these are the fingerprint.
        "sidecar.turn_cancel_requested",
        "sidecar.turn_cancelled",
    }
)

_CLOSE_EVENTS = frozenset({"chat.turn_complete", "chat.resume_complete"})
_START_EVENTS = frozenset({"chat.turn_start"})

# Tail fields whose truth is turn_metrics when a row is present.
_TAIL_METRIC_FIELDS = (
    "status",
    "finish_reason",
    "error",
    "rounds",
    "duration_ms",
    "delegated",
    "workers",
    "input_tokens",
    "output_tokens",
    "boundary_yields",
    "scope_signals",
    "revises",
    "escalations",
)

# L2 compare set: stored turn_metrics ⋈ JSONL close (and collab recompute).
_L2_COMPARE_FIELDS = (
    "finish_reason",
    "delegated",
    "workers",
    "rounds",
    "input_tokens",
    "output_tokens",
    "boundary_yields",
    "scope_signals",
    "revises",
    "escalations",
)

_PHASE0_FIELDS = (
    "prepare_ms",
    "assemble_ms",
    "ttft_reasoning_ms",
    "ttft_content_ms",
)

_DECISION_KEEP_KEYS = (
    "agents",
    "nodes",
    "parallel",
    "call",
    "reason",
    "criteria",
    "gaps",
    "escalate",
    "execution_id",
    "source",
    "streak",
    "run_id",
    "cancelled_run_id",
    "continuation_run_id",
    "kind",
    "question",
    "blocking",
    "assumption",
    "error",
    "scope",
    "scope_ratio",
    "escalations",
    "chars",
    "body_chars",
    "tool",
    "status",
    "rounds",
    "thrashing",
    "token_budget",
    "tokens",
)


def _pick(obj: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: obj[k] for k in keys if k in obj and obj[k] is not None}


def _close_event(log_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    close: dict[str, Any] | None = None
    for ev in log_events:
        if ev.get("event") not in _CLOSE_EVENTS:
            continue
        # Terminal close wins over paused mid-snapshot (same rule as collab_drift).
        if ev.get("finish_reason") == "paused":
            if close is None:
                close = ev
            continue
        close = ev
    return close


def _start_event(log_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for ev in log_events:
        if ev.get("event") in _START_EVENTS:
            return ev
    return None


def _project_decision(ev: dict[str, Any]) -> dict[str, Any]:
    event = str(ev.get("event") or "")
    row: dict[str, Any] = {
        "timestamp": ev.get("timestamp", ""),
        "event": event,
    }
    if ev.get("level") in ("error", "warning"):
        row["level"] = ev["level"]
    detail = _pick(ev, _DECISION_KEEP_KEYS)
    if event == "delegate.started":
        plan = ev.get("plan")
        waves = ev.get("waves")
        if isinstance(plan, list):
            detail["roles"] = [
                n.get("role") or n.get("id") for n in plan if isinstance(n, dict)
            ]
        if waves is not None:
            detail["wave_count"] = len(waves) if isinstance(waves, list) else waves
    if event == "tool.execute_end":
        detail["tool"] = ev.get("tool")
        detail["status"] = ev.get("status")
        if ev.get("reason"):
            detail["reason"] = ev.get("reason")
    row["detail"] = detail
    return row


def _iter_decisions(log_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in log_events:
        event = str(ev.get("event") or "")
        if event in _DECISION_EVENTS:
            out.append(_project_decision(ev))
            continue
        # Obvious tool failures only (success noise stays off the spine).
        if event == "tool.execute_end" and ev.get("status") == "error":
            out.append(_project_decision(ev))
    return out


def _llm_summary(log_events: list[dict[str, Any]]) -> dict[str, Any]:
    calls = 0
    failed = 0
    models: dict[str, int] = {}
    input_tokens = 0
    output_tokens = 0
    cost_nano = 0
    for ev in log_events:
        event = ev.get("event")
        if event == "llm.call":
            calls += 1
            model = ev.get("model")
            if model:
                models[str(model)] = models.get(str(model), 0) + 1
            input_tokens += int(ev.get("input_tokens") or 0)
            output_tokens += int(ev.get("output_tokens") or 0)
            cost_nano += int(ev.get("cost_nano") or 0)
        elif event == "llm.call_failed":
            failed += 1
            model = ev.get("model")
            if model:
                models[str(model)] = models.get(str(model), 0) + 1
    return {
        "calls": calls,
        "failed": failed,
        "models": [{"model": m, "calls": n} for m, n in sorted(models.items())],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_nano": cost_nano,
    }


def _jsonl_collab_recompute(log_events: list[dict[str, Any]]) -> dict[str, Any]:
    rec = new_trace()
    for ev in log_events:
        event = str(ev.get("event") or "")
        if not event:
            continue
        accumulate_trace(rec, event, ev)
    return rec


def _tail_from_close(close: dict[str, Any] | None) -> dict[str, Any]:
    if close is None:
        return {"source": "none"}
    tail: dict[str, Any] = {
        "source": "jsonl_close",
        "event": close.get("event"),
        "finish_reason": close.get("finish_reason"),
        "delegated": bool(close.get("delegated")) if "delegated" in close else None,
        "workers": close.get("workers"),
        "rounds": close.get("rounds"),
        "duration_ms": close.get("duration_ms"),
        "input_tokens": close.get("input_tokens"),
        "output_tokens": close.get("output_tokens"),
        "reply_preview": close.get("reply_preview"),
    }
    for col in COLLAB_FIELD_MAP:
        if col in close:
            tail[col] = int(close.get(col) or 0)
    for f in _PHASE0_FIELDS:
        if f in close:
            tail[f] = close.get(f)
    return {k: v for k, v in tail.items() if v is not None or k == "source"}


def _tail_from_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    tail: dict[str, Any] = {"source": "turn_metrics"}
    for f in _TAIL_METRIC_FIELDS:
        if f in metrics:
            tail[f] = metrics[f]
    if "kind" in metrics:
        tail["kind"] = metrics["kind"]
    if "turn_id" in metrics:
        tail["turn_id"] = metrics["turn_id"]
    return tail


def _normalize_for_compare(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field == "delegated":
        return bool(value)
    if field in (
        "workers",
        "rounds",
        "input_tokens",
        "output_tokens",
        "boundary_yields",
        "scope_signals",
        "revises",
        "escalations",
        "duration_ms",
    ):
        return int(value)
    if field == "finish_reason":
        return str(value)
    return value


def compute_drift_l2(
    *,
    turn_metrics: dict[str, Any] | None,
    close: dict[str, Any] | None,
    recomputed: dict[str, Any],
) -> dict[str, Any]:
    """Compare persisted turn_metrics against JSONL close + event recompute.

    Returns a structured L2 report. ``ok`` is True when metrics exist and every
    comparable field agrees (or the JSONL side has nothing to compare yet).
    """
    if turn_metrics is None:
        return {
            "ok": True,
            "compared": False,
            "reason": "turn_metrics_missing",
            "mismatches": [],
        }

    mismatches: list[dict[str, Any]] = []
    # Prefer terminal JSONL close values; fall back to event recompute for collab.
    close_usable = close is not None and close.get("finish_reason") != "paused"
    close_vals: dict[str, Any] = {}
    if close_usable and close is not None:
        for f in _L2_COMPARE_FIELDS:
            if f in close:
                close_vals[f] = close.get(f)

    recompute_collab = {
        col: int(recomputed.get(trace_field, 0) or 0)
        for col, trace_field in COLLAB_FIELD_MAP.items()
    }

    for field in _L2_COMPARE_FIELDS:
        if field not in turn_metrics:
            continue
        stored = _normalize_for_compare(field, turn_metrics.get(field))
        jsonl_side: Any = None
        jsonl_source: str | None = None
        if field in close_vals:
            jsonl_side = _normalize_for_compare(field, close_vals[field])
            jsonl_source = "jsonl_close"
        elif field in recompute_collab:
            jsonl_side = recompute_collab[field]
            jsonl_source = "jsonl_recompute"
        else:
            continue
        if stored != jsonl_side:
            mismatches.append(
                {
                    "field": field,
                    "turn_metrics": stored,
                    "jsonl": jsonl_side,
                    "jsonl_source": jsonl_source,
                }
            )

    return {
        "ok": len(mismatches) == 0,
        "compared": True,
        "reason": None if mismatches else "aligned",
        "mismatches": mismatches,
    }


def _cost_block(
    cost_events: dict[str, Any] | None,
    log_events: list[dict[str, Any]],
) -> dict[str, Any]:
    if cost_events is not None:
        return {
            "source": "cost_events",
            "total_nano": cost_events.get("total_nano"),
            "currency": cost_events.get("currency"),
            "runs": cost_events.get("runs"),
            "models": cost_events.get("models"),
        }
    for ev in reversed(log_events):
        if ev.get("event") == "cost.recorded":
            return {
                "source": "jsonl_cost.recorded",
                "total_nano": ev.get("total_nano"),
                "total_usd": ev.get("total_usd"),
                "runs": ev.get("runs"),
                "models": ev.get("models"),
                "by_role": ev.get("by_role"),
            }
    return {"source": "none"}


def _drift_l1_for_trace(log_events: list[dict[str, Any]]) -> dict[str, Any]:
    rec = _jsonl_collab_recompute(log_events)
    # collab_drift expects a traces map keyed by trace_id; use a placeholder key.
    tid = "local"
    for ev in log_events:
        if ev.get("trace_id"):
            tid = str(ev["trace_id"])
            break
    return collab_drift({tid: rec})


def build_decision_spine(
    log_events: list[dict[str, Any]],
    *,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    turn_metrics: dict[str, Any] | None = None,
    cost_events: dict[str, Any] | None = None,
    traffic: str | None = None,
    jsonl_gap: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the v0 decision_spine dict (human formatter and ``--json`` share this)."""
    resolved_trace = trace_id
    resolved_cid = conversation_id
    for ev in log_events:
        if not resolved_trace and ev.get("trace_id"):
            resolved_trace = str(ev["trace_id"])
        if not resolved_cid and ev.get("conversation_id"):
            resolved_cid = str(ev["conversation_id"])
        if resolved_trace and resolved_cid:
            break

    start = _start_event(log_events)
    close = _close_event(log_events)
    recomputed = _jsonl_collab_recompute(log_events)

    head: dict[str, Any] = {"source": "none"}
    if start is not None:
        head = {
            "source": "chat.turn_start",
            "timestamp": start.get("timestamp", ""),
            "preview": start.get("preview", ""),
            **_pick(start, ("chars", "history", "location")),
        }

    if turn_metrics is not None:
        tail = _tail_from_metrics(turn_metrics)
        # Phase-0 only lives on JSONL close — attach as evidence, not summary truth.
        if close is not None:
            phase0 = _pick(close, _PHASE0_FIELDS)
            if phase0:
                tail["phase0"] = phase0
            if close.get("reply_preview") and "reply_preview" not in tail:
                tail["reply_preview"] = close.get("reply_preview")
    else:
        tail = _tail_from_close(close)

    drift_l2 = compute_drift_l2(
        turn_metrics=turn_metrics,
        close=close,
        recomputed=recomputed,
    )

    # Paused close is a mid-turn snapshot — still incomplete for the reader.
    incomplete = start is not None and (
        close is None or close.get("finish_reason") == "paused"
    )

    health: dict[str, Any] = {
        "traffic": traffic,
        "incomplete": incomplete,
        "jsonl_gap": jsonl_gap,
        "drift_l1": _drift_l1_for_trace(log_events),
        "drift_l2": drift_l2,
        "turn_metrics_joined": turn_metrics is not None,
        "cost_joined": cost_events is not None,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "trace_id": resolved_trace,
        "conversation_id": resolved_cid,
        "head": head,
        "decisions": _iter_decisions(log_events),
        "llm": _llm_summary(log_events),
        "tail": tail,
        "cost": _cost_block(cost_events, log_events),
        "health": health,
    }


def format_decision_spine(spine: dict[str, Any]) -> str:
    """Human-readable rendering isomorphic to the ``decision_spine`` JSON."""
    lines: list[str] = [
        "=" * 70,
        f"  Decision Spine  ({spine.get('schema_version', SCHEMA_VERSION)})",
        f"  Trace: {spine.get('trace_id') or '?'}",
    ]
    cid = spine.get("conversation_id")
    if cid:
        lines.append(f"  Conversation: {cid}")

    health = spine.get("health") or {}
    if health.get("traffic"):
        lines.append(f"  Traffic: {health['traffic']} (合成流量)")
    if health.get("incomplete"):
        lines.append("  Status: ⚠️ 未完成（进行中或仅 kickoff）")
    gap = health.get("jsonl_gap")
    if gap:
        reason = gap.get("reason", "gap")
        if reason == "timestamp_gap":
            secs = int(gap.get("gap_seconds") or 0)
            lines.append(
                f"  ⚠ jsonl 时间线疑似断档（gap≈{secs}s）；以 Postgres journal 为准"
            )
        else:
            lines.append("  ⚠ jsonl 时间线疑似断档；以 Postgres journal 为准")

    drift_l2 = health.get("drift_l2") or {}
    if drift_l2.get("compared") and not drift_l2.get("ok"):
        n = len(drift_l2.get("mismatches") or [])
        lines.append(f"  ⚠ Drift L2: turn_metrics ⋈ JSONL 不一致（{n} 字段）")
    elif drift_l2.get("compared") and drift_l2.get("ok"):
        lines.append("  Drift L2: aligned")
    elif drift_l2.get("reason") == "turn_metrics_missing":
        lines.append("  Drift L2: (no turn_metrics to join)")

    lines.append("=" * 70)

    head = spine.get("head") or {}
    preview = (head.get("preview") or "").replace("\n", " ").strip() or "(no preview)"
    if len(preview) > 80:
        preview = preview[:77] + "..."
    ts = str(head.get("timestamp") or "")[:19]
    lines.append(f"  Head  {ts}  \"{preview}\"")
    extras = []
    if head.get("history") is not None:
        extras.append(f"history={head['history']}")
    if head.get("chars") is not None:
        extras.append(f"chars={head['chars']}")
    if extras:
        lines.append(f"         {' · '.join(extras)}")

    decisions = spine.get("decisions") or []
    lines.append(f"  Decisions ({len(decisions)})")
    if not decisions:
        lines.append("    (none)")
    for d in decisions:
        dts = str(d.get("timestamp") or "")[:19]
        detail = d.get("detail") or {}
        bits = [f"{k}={v}" for k, v in detail.items()]
        detail_s = " ".join(bits)
        if len(detail_s) > 100:
            detail_s = detail_s[:100] + "..."
        icon = {"error": "[E]", "warning": "[W]"}.get(d.get("level", ""), "   ")
        lines.append(f"    {dts}  {icon} {d.get('event')}  {detail_s}".rstrip())

    llm = spine.get("llm") or {}
    model_bits = ", ".join(
        f"{m['model']}×{m['calls']}" for m in (llm.get("models") or [])
    )
    lines.append(
        f"  LLM  calls={llm.get('calls', 0)} failed={llm.get('failed', 0)}"
        + (f"  [{model_bits}]" if model_bits else "")
        + f"  tok_in={llm.get('input_tokens', 0)} tok_out={llm.get('output_tokens', 0)}"
    )

    tail = spine.get("tail") or {}
    tail_bits = [
        f"source={tail.get('source')}",
        f"finish={tail.get('finish_reason')}",
        f"status={tail.get('status')}" if "status" in tail else None,
        f"delegated={tail.get('delegated')}" if "delegated" in tail else None,
        f"workers={tail.get('workers')}" if "workers" in tail else None,
        f"rounds={tail.get('rounds')}" if "rounds" in tail else None,
        f"dur_ms={tail.get('duration_ms')}" if "duration_ms" in tail else None,
    ]
    collab = []
    for col in COLLAB_FIELD_MAP:
        if col in tail:
            collab.append(f"{col}={tail[col]}")
    lines.append("  Tail  " + " · ".join(b for b in tail_bits if b))
    if collab:
        lines.append("         collab: " + " · ".join(collab))
    if tail.get("error"):
        lines.append(f"         error: {tail['error']}")

    cost = spine.get("cost") or {}
    if cost.get("source") != "none":
        lines.append(
            f"  Cost  source={cost.get('source')}  total_nano={cost.get('total_nano')}"
            + (f"  runs={cost.get('runs')}" if cost.get("runs") is not None else "")
        )
    else:
        lines.append("  Cost  (none)")

    if drift_l2.get("mismatches"):
        lines.append("  Drift L2 mismatches:")
        for m in drift_l2["mismatches"][:8]:
            lines.append(
                f"    - {m['field']}: turn_metrics={m['turn_metrics']} "
                f"jsonl={m['jsonl']} ({m.get('jsonl_source')})"
            )

    lines.append("")
    return "\n".join(lines)
