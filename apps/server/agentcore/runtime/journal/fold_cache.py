"""In-process memoization of the journal→runs DISPLAY projection (项目审计-成本性能专项 PERF-003).

A history page re-projects EVERY assistant message's replay payload from its journal on
every load: :func:`fold.runs_from_entries` is a per-row Python fold (team graph / process
timeline / synthetic deltas), run once per message per request. That fold is a PURE
function of a turn's journal entries, and the §8.3 journal is APPEND-ONLY per turn (a
resume only appends; a completed turn's facts never mutate in place). So the projection is
stable until the journal grows — we memoize it keyed by (message_id, entry count, last
fact's ts+kind): an unchanged journal hits the cache (skips the fold), an appended one gets
a fresh key and recomputes.

Contract- and UX-preserving: the route still returns ``runs`` eagerly so inline team graphs
render on load (the client folds them from ``runs`` at list time, not lazily); we only stop
recomputing the SAME projection across requests (conversation reopen, latest-window reload
after each new turn, scroll-back). A cache MISS is just the original fold, so correctness
never depends on the cache — it can be wiped or disabled with zero behavior change. Bounded
LRU, in-process (per worker); under FastAPI the route folds synchronously between awaits, so
the ``OrderedDict`` needs no lock.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .fold import runs_from_entries

# Bounded LRU over projected payloads. A debate turn's runs dict can be tens of KB, so we
# cap by ENTRY COUNT (not bytes) at a modest size — plenty to cover the turns a user
# browses in a session while keeping worst-case memory small.
_MAX_ENTRIES = 1024
_cache: OrderedDict[str, dict[str, Any] | None] = OrderedDict()


def _version_key(message_id: str, entries: list[dict[str, Any]]) -> str:
    """A cheap O(1) version of an append-only journal: id + count + last fact's ts & kind.

    Any append (resume) grows the count and stamps a new trailing fact, so the key changes
    and we recompute; an idempotent re-persist of identical facts keeps the same key (the
    projection is byte-identical anyway). Relies on the journal being append-only per turn
    (§8.3) — facts are never rewritten in place at the same length.
    """
    last = entries[-1]
    return f"{message_id}|{len(entries)}|{last.get('ts')}|{last.get('kind')}"


def runs_from_entries_cached(
    message_id: str, entries: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """:func:`runs_from_entries` memoized per (message, journal version) — see module doc.

    Returns the SAME projected dict object on a hit, so callers MUST treat it as read-only
    (the messages route only feeds it to ``RunsPayload.model_validate``, which copies — it
    never mutates the projection).
    """
    if not entries:
        # No journal → plain bubble (the fold's own None-gate); nothing to memoize.
        return None
    key = _version_key(message_id, entries)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    runs = runs_from_entries(entries)
    _cache[key] = runs  # newest → already at the end (insertion order)
    if len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)
    return runs


def clear_runs_cache() -> None:
    """Drop all memoized projections (test isolation / manual flush)."""
    _cache.clear()
