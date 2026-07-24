"""Serial write-behind journal writer: bounded to one connection + turn-end drain.

The prior model fanned out a task-(and-connection-)per-fact; under a wide parallel
delegation that stormed the pool (asyncpg ``connection_lost`` + non-checked-in-connection
GC). These tests pin the new invariants: at most one in-flight write (no fan-out storm),
emit-ordered ``seq``, every Future resolved (the SSE barrier can never hang), and
best-effort degradation that still drains the rest.
"""

from __future__ import annotations

import asyncio

from agentcore.runtime.journal.writer import TurnJournalWriter


class _SessionTracker:
    """Counts concurrently-open fake sessions so a fan-out regression shows as max_open > 1."""

    def __init__(self) -> None:
        self.open = 0
        self.max_open = 0

    def factory(self) -> _FakeSession:
        return _FakeSession(self)


class _FakeSession:
    def __init__(self, tracker: _SessionTracker) -> None:
        self._t = tracker

    async def __aenter__(self) -> _FakeSession:
        self._t.open += 1
        self._t.max_open = max(self._t.max_open, self._t.open)
        return self

    async def __aexit__(self, *exc: object) -> bool:
        self._t.open -= 1
        return False


def _patch(monkeypatch, tracker: _SessionTracker, repo_cls: type) -> None:
    monkeypatch.setattr(
        "agentcore.conversation.store.cloud.telemetry_session_factory", tracker.factory
    )
    monkeypatch.setattr(
        "agentcore.conversation.store.cloud.TurnJournalRepository", repo_cls
    )
    monkeypatch.setattr(
        "agentcore.runtime.audit.hooks.on_journal_fact_appended", lambda entry: None
    )


async def test_appends_serialized_ordered_and_all_futures_resolve(monkeypatch) -> None:
    tracker = _SessionTracker()
    written: list[int] = []

    class Repo:
        def __init__(self, session: object) -> None:
            pass

        async def append(self, *, turn_id, seq, conversation_id, trace_id, entry) -> int | None:
            # Yield twice: an overlapping (fanned-out) drain would surface as max_open > 1.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            written.append(seq)
            return len(written) - 1

    _patch(monkeypatch, tracker, Repo)
    writer = TurnJournalWriter(turn_id="m1", conversation_id="c1", trace_id="t1")

    futures = [writer.schedule_append({"kind": f"k{i}"}) for i in range(25)]
    await writer.flush()

    assert tracker.max_open == 1  # bounded to a single connection — no fan-out storm
    # D7 live: seq=None（DB 分配）；仍串行、emit 序、Future 全 resolve
    assert written == [None] * 25
    assert all(f is not None and f.done() for f in futures)
    assert writer.degraded is False


async def test_write_failure_degrades_but_never_hangs(monkeypatch) -> None:
    tracker = _SessionTracker()
    written: list[int] = []

    class Repo:
        def __init__(self, session: object) -> None:
            pass

        async def append(self, *, turn_id, seq, conversation_id, trace_id, entry) -> int | None:
            if entry.get("kind") == "bad":
                raise RuntimeError("boom")
            written.append(seq)
            return len(written) - 1

    _patch(monkeypatch, tracker, Repo)
    writer = TurnJournalWriter(turn_id="m1", conversation_id="c1", trace_id="t1")

    f_ok = writer.schedule_append({"kind": "ok"})
    f_bad = writer.schedule_append({"kind": "bad"})
    f_ok2 = writer.schedule_append({"kind": "ok2"})
    await writer.flush()

    assert writer.degraded is True  # the failure is surfaced (turn journal degraded)
    assert written == [None, None]  # bad skipped; live seq=None
    assert all(f is not None and f.done() for f in (f_ok, f_bad, f_ok2))  # none hang


async def test_flush_without_any_appends_is_noop() -> None:
    writer = TurnJournalWriter(turn_id="m1", conversation_id="c1", trace_id="t1")
    await writer.flush()  # no drain task ever started → returns immediately
    assert writer.degraded is False


async def test_seal_stops_further_durable_appends(monkeypatch) -> None:
    """After seal, schedule_append must not write more DB rows (pause hard boundary)."""
    tracker = _SessionTracker()
    written: list[int] = []

    class Repo:
        def __init__(self, session: object) -> None:
            pass

        async def append(self, *, turn_id, seq, conversation_id, trace_id, entry) -> int | None:
            written.append(seq)
            return len(written) - 1

    _patch(monkeypatch, tracker, Repo)
    writer = TurnJournalWriter(turn_id="m1", conversation_id="c1", trace_id="t1")

    f0 = writer.schedule_append({"kind": "pre"})
    await writer.seal()

    assert writer.sealed is True
    assert writer.next_seq == 1
    assert written == [None]
    assert f0 is not None and f0.done()

    # Post-seal appends are durable no-ops: no Future, no seq bump, no DB write.
    assert writer.schedule_append({"kind": "post"}) is None
    assert writer.schedule_append({"kind": "post2"}) is None
    await writer.flush()
    assert written == [None]
    assert writer.next_seq == 1

    # Idempotent seal.
    await writer.seal()
    assert writer.sealed is True
    assert written == [None]
