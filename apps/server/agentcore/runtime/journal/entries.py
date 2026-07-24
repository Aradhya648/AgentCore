"""Journal entry serialization (write path: runs payload → ordered facts)."""

from __future__ import annotations

from typing import Any

# Journal kind for the per-turn outcome fact (finish_reason). The run/tool/
# interaction facts keep their SSE event type as their kind; single-agent process
# steps are prefixed so the two lanes are distinguishable in the table.
KIND_TURN_END = "turn_end"
_PROCESS_PREFIX = "process_"
# Per-worker-run process lane (对称 CEO ``process_``): kind carries the step kind;
# ``payload.run_id`` scopes the step to its run node.
_RUN_PROCESS_PREFIX = "run_process_"


def entries_from_runs(runs: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten an in-memory ``runs`` replay payload into ordered journal entries.

    ``runs`` is the sink-built ``{events, finish_reason, process?, run_processes?}``
    payload (see ``runtime/pipeline._build_runs_payload``). Each entry is
    ``{kind, payload, ts}`` in emission order: the team-graph ``events`` first (each
    keeping its SSE event type as ``kind`` + original ``timestamp`` as ``ts``), then
    any single-agent ``process`` steps (kind-prefixed), then per-run worker process
    steps, then a closing ``turn_end`` carrying the finish reason. Returns ``[]`` for
    an empty / absent payload.
    """
    if not runs:
        return []
    entries: list[dict[str, Any]] = []
    for ev in runs.get("events") or []:
        entries.append(
            {
                "kind": ev.get("type") or "",
                "payload": ev.get("payload") or {},
                "ts": ev.get("timestamp"),
            }
        )
    for step in runs.get("process") or []:
        entries.append(
            {
                "kind": f"{_PROCESS_PREFIX}{step.get('kind') or 'step'}",
                "payload": step,
                "ts": None,
            }
        )
    for run_id, steps in (runs.get("run_processes") or {}).items():
        for step in steps or []:
            entries.append(
                {
                    "kind": f"{_RUN_PROCESS_PREFIX}{step.get('kind') or 'step'}",
                    "payload": {**step, "run_id": run_id},
                    "ts": None,
                }
            )
    # turn_end (the per-turn outcome fact): finish_reason + an optional error. A 报错回合
    # carries its error here so the inline error card replays on reload (Tier 2 a) — the
    # live error rides a transport-only ``error`` SSE event (never journaled), so this
    # outcome fact is its only durable home. Emitted when EITHER is present.
    finish_reason = runs.get("finish_reason")
    run_error = runs.get("error")
    if finish_reason is not None or run_error is not None:
        payload: dict[str, Any] = {"finish_reason": finish_reason}
        if run_error is not None:
            payload["error"] = run_error
        entries.append({"kind": KIND_TURN_END, "payload": payload, "ts": None})
    return entries


def journal_entries_from_display_runs(runs: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Flatten a display ``runs`` replay payload into durable journal entries (or None).

    Single write-side entry for paths that hold a replay dict but no live
    :class:`~agentcore.runtime.events.EventSink` — local-relay write-back, incomplete
    salvage, abnormal-outcome synth, and the display-only branch of pipeline finalize.
    Returns ``None`` when ``runs`` is absent or flattens to nothing persistable.
    """
    if not runs:
        return None
    entries = entries_from_runs(runs)
    return entries if entries else None
