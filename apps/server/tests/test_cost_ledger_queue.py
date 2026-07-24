"""Shared cost ledger durable queue: turn/handoff enqueue + drain."""

from __future__ import annotations

import json

import pytest

from agentcore.billing import cost_ledger_queue as queue_mod


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


@pytest.fixture
def ledger_queue(monkeypatch, tmp_path):
    queue = queue_mod.reset_cost_ledger_queue_for_tests()
    monkeypatch.setattr(queue_mod.settings, "data_dir", str(tmp_path))
    return queue


def _sample_runs(*, run_id: str = "run-1") -> list[dict]:
    return [
        {
            "run_id": run_id,
            "agent_id": "CEO",
            "role": "captain",
            "model": "m",
            "tokens": {"input": 1, "output": 2},
            "cost": {},
            "cost_total_nano": 0,
            "currency": "USD",
            "rounds": 1,
            "duration_ms": 10,
        }
    ]


async def test_enqueue_runs_then_drain_records(monkeypatch, ledger_queue, tmp_path):
    calls: list = []

    class Repo:
        def __init__(self, _session):
            pass

        async def record_runs(self, **kw):
            calls.append(kw)
            return 1

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _FakeSession())
    monkeypatch.setattr("agentcore.db.repositories.CostEventRepository", Repo)

    rid = ledger_queue.enqueue_runs(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        trace_id="t1",
        runs=_sample_runs(),
        source="turn",
    )
    assert rid is not None
    files = list((tmp_path / "telemetry" / "cost_ledger_queue").glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["source"] == "turn"
    assert payload["runs"][0]["run_id"] == "run-1"

    assert await ledger_queue.drain_once() == 1
    assert calls and calls[0]["message_id"] == "m1"
    assert calls[0]["runs"][0]["run_id"] == "run-1"
    assert list((tmp_path / "telemetry" / "cost_ledger_queue").glob("*.json")) == []


async def test_drain_retries_after_write_failure(monkeypatch, ledger_queue, tmp_path):
    """Sync write failed → enqueue; first drain fails; second drain succeeds."""
    attempts = {"n": 0}
    calls: list = []

    class Repo:
        def __init__(self, _session):
            pass

        async def record_runs(self, **kw):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("db down")
            calls.append(kw)
            return 1

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _FakeSession())
    monkeypatch.setattr("agentcore.db.repositories.CostEventRepository", Repo)

    ledger_queue.enqueue_runs(
        user_id="u1",
        conversation_id="c1",
        message_id="m1",
        runs=_sample_runs(run_id="run-retry"),
        source="handoff",
    )
    assert await ledger_queue.drain_once() == 0
    assert list((tmp_path / "telemetry" / "cost_ledger_queue").glob("*.json"))
    assert calls == []

    assert await ledger_queue.drain_once() == 1
    assert calls[0]["runs"][0]["run_id"] == "run-retry"
    assert list((tmp_path / "telemetry" / "cost_ledger_queue").glob("*.json")) == []


async def test_drains_legacy_proxy_spend_dir(monkeypatch, ledger_queue, tmp_path):
    """Files left in the old proxy_spend_queue path are still consumed."""
    calls: list = []

    class Repo:
        def __init__(self, _session):
            pass

        async def record_runs(self, **kw):
            calls.append(kw)
            return 1

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _FakeSession())
    monkeypatch.setattr("agentcore.db.repositories.CostEventRepository", Repo)

    legacy = tmp_path / "telemetry" / "proxy_spend_queue"
    legacy.mkdir(parents=True)
    (legacy / "legacy.json").write_text(
        json.dumps(
            {
                "id": "legacy-1",
                "user_id": "u1",
                "conversation_id": "c1",
                "runs": _sample_runs(run_id="legacy-run"),
            }
        ),
        encoding="utf-8",
    )
    assert await ledger_queue.drain_once() == 1
    assert calls[0]["runs"][0]["run_id"] == "legacy-run"
