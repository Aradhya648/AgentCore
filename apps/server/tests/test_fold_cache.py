"""Tests for the journal→runs projection cache (项目审计-成本性能专项 PERF-003).

The cache MUST be transparent: the SAME projection as the uncached fold, memoized per
(message, journal version), and invalidated the moment the journal grows (a resume append).
"""

from agentcore.runtime.journal import fold_cache, runs_from_entries, runs_from_entries_cached
from agentcore.runtime.journal.fold_cache import clear_runs_cache


def _surfaced() -> list[dict]:
    # A delegated turn (run_plan surfaces the team graph) → projects to a non-None runs.
    return [
        {"kind": "run_plan", "payload": {"execution_id": "e1"}, "ts": "t0"},
        {"kind": "run_started", "payload": {"run_id": "w1"}, "ts": "t1"},
        {"kind": "run_completed", "payload": {"run_id": "w1"}, "ts": "t2"},
        {"kind": "turn_end", "payload": {"finish_reason": "end_turn"}, "ts": "t3"},
    ]


def test_cached_matches_uncached_fold():
    clear_runs_cache()
    entries = _surfaced()
    # Transparency: caching never changes WHAT is projected.
    assert runs_from_entries_cached("m1", entries) == runs_from_entries(entries)


def test_repeated_call_is_memoized_same_object():
    clear_runs_cache()
    entries = _surfaced()
    first = runs_from_entries_cached("m1", entries)
    second = runs_from_entries_cached("m1", entries)
    # A cache HIT returns the very same projected object — the fold ran once (the win).
    assert first is second


def test_clear_forces_recompute():
    clear_runs_cache()
    entries = _surfaced()
    first = runs_from_entries_cached("m1", entries)
    clear_runs_cache()
    second = runs_from_entries_cached("m1", entries)
    # After a flush the projection is recomputed (equal value, fresh object).
    assert first == second and first is not second


def test_appended_journal_invalidates():
    clear_runs_cache()
    entries = _surfaced()
    first = runs_from_entries_cached("m1", entries)
    # A resume appends a fact before the closing turn_end → the version (count) changes.
    grown = entries[:-1] + [
        {"kind": "run_started", "payload": {"run_id": "w2"}, "ts": "t4"},
        entries[-1],
    ]
    second = runs_from_entries_cached("m1", grown)
    assert second is not first  # new version → recompute, not the stale hit
    assert second != first  # and it reflects the new fact
    assert second == runs_from_entries(grown)


def test_keyed_by_message_id_not_shared_across_messages():
    clear_runs_cache()
    entries = _surfaced()
    a = runs_from_entries_cached("mA", entries)
    b = runs_from_entries_cached("mB", entries)
    # Different messages cache independently (keyed by id) — both still correct.
    assert a == b == runs_from_entries(entries)


def test_empty_or_none_returns_none_without_caching():
    clear_runs_cache()
    assert runs_from_entries_cached("m1", None) is None
    assert runs_from_entries_cached("m1", []) is None
    # A no-journal turn is the fold's own None-gate; nothing is memoized for it.
    assert len(fold_cache._cache) == 0


def test_lru_eviction_bounds_size(monkeypatch):
    clear_runs_cache()
    monkeypatch.setattr(fold_cache, "_MAX_ENTRIES", 3)
    for i in range(5):
        runs_from_entries_cached(f"m{i}", _surfaced())  # distinct ids → distinct keys
    # The LRU never grows past its bound (oldest entries evicted).
    assert len(fold_cache._cache) == 3
