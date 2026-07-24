"""proxy_spend durable queue: drain, idempotent run_id dedupe, telemetry pool isolation."""

from __future__ import annotations

import json

import pytest

from agentcore.billing import cost_ledger_queue as ledger_mod
from agentcore.billing import proxy_spend_queue as queue_mod
from agentcore.llm.provider.protocol import TokenUsage


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _usage() -> TokenUsage:
    return TokenUsage(input_tokens=10, output_tokens=2)


@pytest.fixture
def spend_queue(monkeypatch, tmp_path):
    queue = queue_mod.reset_proxy_spend_queue_for_tests()
    monkeypatch.setattr(ledger_mod.settings, "data_dir", str(tmp_path))
    return queue


async def test_enqueue_writes_disk_then_drain_records(monkeypatch, spend_queue, tmp_path):
    calls: list = []

    class Repo:
        def __init__(self, _session):
            pass

        async def record_calls(self, **kw):
            calls.append(kw)
            return 1

        async def record_runs(self, **kw):
            raise AssertionError("proxy path should materialize via record_calls")

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _FakeSession())
    monkeypatch.setattr("agentcore.db.repositories.CostEventRepository", Repo)

    rid = spend_queue.enqueue(
        user_id="u1",
        conversation_id="c1",
        model="deepseek-v4-flash",
        usage=_usage(),
        message_id="m1",
        trace_id="t1",
        run_id="run-1",
        role="member",
        persona="调研员",
    )
    assert rid is not None
    files = list((tmp_path / "telemetry" / "cost_ledger_queue").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["calls"][0]["persona"] == "调研员"
    assert payload["calls"][0]["run_id"] == "run-1"
    assert payload["materialize_runs"] is True

    assert await spend_queue.drain_once() == 1
    assert calls and calls[0]["message_id"] == "m1"
    assert calls[0]["calls"][0]["call_id"]
    assert calls[0]["materialize_runs"] is True
    # Acked — file gone.
    assert list((tmp_path / "telemetry" / "cost_ledger_queue").glob("*.json")) == []


async def test_drain_retry_same_call_id_no_double_bill(monkeypatch, spend_queue, tmp_path):
    """At-least-once: re-draining the same record must reuse call_id (ledger dedupes)."""
    seen_call_ids: list[str] = []

    class Repo:
        def __init__(self, _session):
            pass

        async def record_calls(self, **kw):
            seen_call_ids.append(kw["calls"][0]["call_id"])
            return 1

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _FakeSession())
    monkeypatch.setattr("agentcore.db.repositories.CostEventRepository", Repo)

    spend_queue.enqueue(
        user_id="u1",
        conversation_id="c1",
        model="m",
        usage=_usage(),
    )
    qdir = tmp_path / "telemetry" / "cost_ledger_queue"
    files = list(qdir.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    call_id = payload["calls"][0]["call_id"]

    assert await spend_queue.drain_once() == 1
    assert seen_call_ids == [call_id]

    files[0].write_text(json.dumps(payload), encoding="utf-8")
    assert await spend_queue.drain_once() == 1
    assert seen_call_ids == [call_id, call_id]


async def test_survives_process_restart_via_disk(monkeypatch, spend_queue, tmp_path):
    """Files left on disk after a crash are drained by a fresh queue instance."""
    calls: list = []

    class Repo:
        def __init__(self, _session):
            pass

        async def record_calls(self, **kw):
            calls.append(kw)
            return 1

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _FakeSession())
    monkeypatch.setattr("agentcore.db.repositories.CostEventRepository", Repo)

    spend_queue.enqueue(
        user_id="u1",
        conversation_id="c1",
        model="m",
        usage=_usage(),
    )
    # New process = new queue singleton; disk still has the file.
    restarted = queue_mod.reset_proxy_spend_queue_for_tests()
    monkeypatch.setattr(ledger_mod.settings, "data_dir", str(tmp_path))
    assert await restarted.drain_once() == 1
    assert len(calls) == 1


async def test_journal_uses_telemetry_pool_not_primary(monkeypatch):
    """Journal drain must check out the telemetry factory (pool isolation)."""
    from agentcore.runtime.journal.writer import TurnJournalWriter

    used: list[str] = []

    class Tracker:
        def factory(self):
            used.append("telemetry")
            return _FakeSession()

    class Repo:
        def __init__(self, _session):
            pass

        async def append(self, **_kw):
            return None

    def primary_boom():
        used.append("primary")
        raise AssertionError("journal must not use the primary pool")

    monkeypatch.setattr(
        "agentcore.conversation.store.cloud.telemetry_session_factory", Tracker().factory
    )
    monkeypatch.setattr("agentcore.conversation.store.cloud.async_session_factory", primary_boom)
    monkeypatch.setattr("agentcore.conversation.store.cloud.TurnJournalRepository", Repo)
    monkeypatch.setattr(
        "agentcore.runtime.audit.hooks.on_journal_fact_appended", lambda entry: None
    )

    writer = TurnJournalWriter(turn_id="m1", conversation_id="c1", trace_id="t1")
    fut = writer.schedule_append({"kind": "k"})
    await writer.flush()
    assert fut is not None and fut.done()
    assert used == ["telemetry"]
