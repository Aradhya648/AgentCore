"""Unit tests for the offline 协作质量方向盘 (scripts/log_stats.py §2.5).

Pin the per-trace fold + the four MAST-labeled metrics it prints. ``scripts/`` is not
a package, so load the module by file path (no sys.path mutation)."""

import importlib.util
from collections import Counter
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "log_stats", Path(__file__).resolve().parents[1] / "scripts" / "log_stats.py"
)
log_stats = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(log_stats)


def test_accumulate_trace_folds_every_collab_signal():
    rec = log_stats._new_trace()
    for event, obj in [
        ("chat.turn_complete", {"delegated": True, "finish_reason": "end_turn"}),
        ("contract.retry", {}),
        ("delegate.continuation_ok", {}),
        ("delegate.continuation_ok", {}),
        ("delegate.started", {}),
        ("delegate.completed", {"escalations": 4, "scope": 1, "scope_ratio": 0.5}),
        ("delegate.yielded", {"reason": "scope"}),
        ("engine.loop_nudge", {}),
    ]:
        log_stats._accumulate_trace(rec, event, obj)

    assert rec["turn"] is True
    assert rec["delegated"] is True
    assert rec["finish_reason"] == "end_turn"
    assert rec["contract_retry"] == 1
    assert rec["revise"] == 2
    assert rec["delegate_batches"] == 1
    assert rec["escalations"] == 4
    assert rec["scope_boundaries"] == 1
    assert rec["scope_ratio_sum"] == 0.5 and rec["scope_ratio_n"] == 1
    assert rec["yields"] == 1 and rec["scope_yields"] == 1
    assert rec["loop_nudge"] == 1


def _line(out: str, needle: str) -> str:
    return next(ln for ln in out.splitlines() if needle in ln)


def test_collaboration_quality_metrics_over_traces(capsys):
    # Three turns: one clean delegated, one delegated that yielded (replan) + drifted + revised,
    # and one plain single-agent turn. Pin the four headline rates (spacing-robust).
    clean = log_stats._new_trace()
    for e, o in [("chat.turn_complete", {"delegated": True}), ("delegate.started", {})]:
        log_stats._accumulate_trace(clean, e, o)
    messy = log_stats._new_trace()
    for e, o in [
        ("chat.turn_complete", {"delegated": True}),
        ("delegate.started", {}),
        ("delegate.completed", {"escalations": 2, "scope": 0, "scope_ratio": 0.0}),
        ("delegate.yielded", {"reason": "scope"}),
        ("delegate.continuation_ok", {}),
    ]:
        log_stats._accumulate_trace(messy, e, o)
    plain = log_stats._new_trace()
    log_stats._accumulate_trace(plain, "chat.turn_complete", {"delegated": False})

    log_stats._print_collaboration_quality({"a": clean, "b": messy, "c": plain})
    out = capsys.readouterr().out

    assert "Turns 3  (delegated 2)" in out
    assert "50.0%" in _line(out, "首计划存活率")  # 1 of 2 delegated ran first plan clean
    assert "50.0%" in _line(out, "漂移率")  # 1 of 2 delegated turns drifted (scope)
    assert "33.3%" in _line(out, "返工率")  # 1 of 3 turns had a revise


def test_convergence_governance_splits_in_turn_vs_orphan(capsys):
    # A completed turn that nudged once, plus orphan events (an eval/test run, or a trace
    # whose turn never completed): the split must attribute in-turn vs orphan so the raw
    # totals reconcile with the turn-grouped 空转率 (no more silent gap).
    turn = log_stats._new_trace()
    for e, o in [("chat.turn_complete", {"delegated": False}), ("engine.loop_nudge", {})]:
        log_stats._accumulate_trace(turn, e, o)
    orphan = log_stats._new_trace()  # never logged chat.turn_complete
    log_stats._accumulate_trace(orphan, "engine.loop_nudge", {})
    log_stats._accumulate_trace(orphan, "engine.ceiling_finalize", {"reason": "max_rounds"})

    events = Counter({"engine.loop_nudge": 2, "engine.ceiling_finalize": 1})
    log_stats._print_convergence_governance(events, {"a": turn, "b": orphan})
    out = capsys.readouterr().out

    assert "(1 in turns, 1 orphan)" in _line(out, "engine.loop_nudge")
    assert "(0 in turns, 1 orphan)" in _line(out, "engine.ceiling_finalize")


def test_convergence_governance_ceiling_reason_breakdown(capsys):
    # engine.ceiling_finalize is the real hard-ceiling event (ceiling.py): reason=
    # max_rounds carries the retired engine.max_rounds_exhausted「轮预算耗尽」semantics.
    turn = log_stats._new_trace()
    for e, o in [
        ("chat.turn_complete", {"delegated": True}),
        ("engine.ceiling_finalize", {"reason": "max_rounds"}),
        ("engine.ceiling_finalize", {"reason": "token_budget"}),
    ]:
        log_stats._accumulate_trace(turn, e, o)

    events = Counter({"engine.ceiling_finalize": 2})
    reasons = Counter({"max_rounds": 1, "token_budget": 1})
    log_stats._print_convergence_governance(events, {"a": turn}, reasons)
    out = capsys.readouterr().out

    line = _line(out, "engine.ceiling_finalize")
    assert "max_rounds×1" in line and "token_budget×1" in line


def test_convergence_governance_no_orphan_note_when_all_in_turn(capsys):
    # When every governance event belongs to a completed turn, no orphan note is shown
    # (the clean case — raw totals already equal the turn-grouped counts).
    turn = log_stats._new_trace()
    for e in ("chat.turn_complete", "engine.loop_finalize"):
        log_stats._accumulate_trace(turn, e, {})
    log_stats._print_convergence_governance(Counter({"engine.loop_finalize": 1}), {"a": turn})
    out = capsys.readouterr().out
    assert "engine.loop_finalize" in out
    assert "orphan" not in out


def test_collaboration_quality_silent_without_turns(capsys):
    # No completed turns in the window → no section printed (a trace with only sub-events
    # but no chat.turn_complete is an incomplete/rotated trace, correctly excluded).
    orphan = log_stats._new_trace()
    log_stats._accumulate_trace(orphan, "engine.ceiling_finalize", {"reason": "max_rounds"})
    log_stats._print_collaboration_quality({"x": orphan})
    assert capsys.readouterr().out == ""


def _turn_events(collab: dict, events: list[tuple[str, dict]]) -> dict:
    """Fold a synthetic turn: delegate.* events + a turn_complete carrying the
    runtime counters (the exact shape turn_runner.py logs)."""
    rec = log_stats._new_trace()
    for e, o in events:
        log_stats._accumulate_trace(rec, e, o)
    log_stats._accumulate_trace(
        rec, "chat.turn_complete", {"delegated": True, **collab}
    )
    return rec


def test_collab_drift_silent_when_tracks_agree(capsys):
    # 双轨对账 golden: runtime counters on turn_complete == event-recomputed tally
    # (one yielded boundary, one scope escalation batch, one continuation).
    rec = _turn_events(
        {"boundary_yields": 1, "scope_signals": 1, "revises": 1, "escalations": 2},
        [
            ("delegate.started", {}),
            ("delegate.yielded", {"reason": "scope"}),
            ("delegate.completed", {"escalations": 2, "scope": 1, "scope_ratio": 0.5}),
            ("delegate.continuation_ok", {}),
        ],
    )
    drift = log_stats.collab_drift({"t1": rec})
    assert drift["checked_turns"] == 1
    assert drift["by_field"] == {}

    log_stats._print_collaboration_quality({"t1": rec})
    assert "双轨漂移" not in capsys.readouterr().out


def test_collab_drift_rings_on_divergence(capsys):
    # One implementation changes semantics (runtime reports 0 revises while the
    # event stream shows a continuation) → the reconciliation must ring.
    rec = _turn_events(
        {"boundary_yields": 0, "scope_signals": 0, "revises": 0, "escalations": 0},
        [("delegate.started", {}), ("delegate.continuation_ok", {})],
    )
    drift = log_stats.collab_drift({"t1": rec})
    assert drift["by_field"] == {"revises": 1}
    assert drift["samples"][0]["reported"] == 0
    assert drift["samples"][0]["recomputed"] == 1

    log_stats._print_collaboration_quality({"t1": rec})
    out = capsys.readouterr().out
    assert "双轨漂移" in out and "revises×1" in out


def test_collab_drift_skips_legacy_lines_without_counters():
    # Pre-upgrade turn_complete lines carry no collab counters — not drift.
    rec = log_stats._new_trace()
    log_stats._accumulate_trace(rec, "delegate.continuation_ok", {})
    log_stats._accumulate_trace(rec, "chat.turn_complete", {"delegated": True})
    drift = log_stats.collab_drift({"t1": rec})
    assert drift["checked_turns"] == 0
    assert drift["by_field"] == {}


def _zeros() -> dict:
    return {"boundary_yields": 0, "scope_signals": 0, "revises": 0, "escalations": 0}


def test_collab_drift_pause_resume_uses_terminal_close_not_paused_snapshot():
    # The d15ca428 case: turn pauses at ask_user (snapshot reports all zeros),
    # the resumed segment escalates once, and the terminal resume_complete now
    # carries the runtime counters. The paused snapshot must NOT be authority —
    # pre-fix this misreported escalations 0 vs 1; post-fix it is silent.
    rec = log_stats._new_trace()
    for e, o in [
        ("chat.turn_complete", {"finish_reason": "paused", "delegated": False, **_zeros()}),
        ("delegate.started", {}),
        ("delegate.completed", {"escalations": 0, "scope": 0, "scope_ratio": 0.0}),
        ("delegate.started", {}),
        ("worker.escalate", {"kind": "normal", "blocking": False}),
        ("delegate.completed", {"escalations": 1, "scope": 0, "scope_ratio": 0.0}),
        (
            "chat.resume_complete",
            {"finish_reason": "end_turn", "delegated": True, **_zeros(), "escalations": 1},
        ),
    ]:
        log_stats._accumulate_trace(rec, e, o)

    assert rec["reported_collab"]["escalations"] == 1  # terminal close won
    drift = log_stats.collab_drift({"d15ca428": rec})
    assert drift["checked_turns"] == 1
    assert drift["by_field"] == {}


def test_collab_drift_pause_resume_without_terminal_counters_is_unreconcilable():
    # Same shape but the terminal close carries no counters (legacy resume line /
    # STOP resume): the paused snapshot must not be used → 不可对账, not drift.
    rec = log_stats._new_trace()
    for e, o in [
        ("chat.turn_complete", {"finish_reason": "paused", "delegated": False, **_zeros()}),
        ("delegate.completed", {"escalations": 1, "scope": 0, "scope_ratio": 0.0}),
        ("chat.resume_complete", {"finish_reason": "end_turn", "delegated": True}),
    ]:
        log_stats._accumulate_trace(rec, e, o)

    assert rec["reported_collab"] is None
    drift = log_stats.collab_drift({"t1": rec})
    assert drift["checked_turns"] == 0
    assert drift["by_field"] == {}


def test_collab_drift_counts_redirect_hot_as_revise():
    # runtime note_continuation covers continue_from AND redirect 热修 — the
    # recomputed revise bucket must count delegate.run_redirect_hot too, else
    # every hot redirect would ring as revises drift.
    rec = _turn_events(
        {"boundary_yields": 0, "scope_signals": 0, "revises": 2, "escalations": 0},
        [
            ("delegate.started", {}),
            ("delegate.continuation_ok", {}),
            ("delegate.run_redirect_hot", {"continuation_run_id": "r2"}),
        ],
    )
    assert rec["revise"] == 2
    drift = log_stats.collab_drift({"t1": rec})
    assert drift["checked_turns"] == 1
    assert drift["by_field"] == {}
