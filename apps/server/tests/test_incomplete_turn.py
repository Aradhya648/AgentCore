"""Unit tests for disconnect-salvage of a turn's finished work (断线别白干).

A turn cancelled mid-flight (client disconnect / user stop / pending approval) used
to discard workers that had ALREADY finished. The salvage path persists that finished
work as one "incomplete" assistant message instead. These cover:

- ``has_open_durable_pause`` — which journals count as a live resume frame (so salvage
  defers to ``POST .../resume`` rather than double-handling the turn);
- ``salvage_incomplete_turn`` — the spawn decision (gate / empty journal / durable
  pause deferral vs. fire);
- ``persist_incomplete_turn`` — the persisted message shape (cancelled flag, journal,
  no ledger).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentcore.config import settings
from agentcore.conversation import turn_persistence
from agentcore.conversation.turn_persistence import (
    has_open_durable_pause,
    persist_incomplete_turn,
    salvage_incomplete_turn,
)
from agentcore.runtime.events import FinishReason


def _ev(type_: str, checkpoint_id: str | None = None) -> dict:
    payload = {"checkpoint_id": checkpoint_id} if checkpoint_id else {}
    return {"type": type_, "payload": payload}


class _Sink:
    """Minimal stand-in for EventSink — ``execution_journal`` + ``streamed_content`` are read."""

    def __init__(self, journal: list[dict] | None, content: str = "") -> None:
        self._journal = journal
        self._content = content

    def execution_journal(self) -> list[dict] | None:
        return self._journal

    def streamed_content(self) -> str:
        return self._content


# --- _has_open_durable_pause ---


def test_open_pause_false_on_empty_journal():
    assert has_open_durable_pause([]) is False


def test_open_pause_true_on_unresolved_checkpoint():
    assert has_open_durable_pause([_ev("checkpoint_required", "c1")]) is True


def test_open_pause_true_on_unresolved_plan_review():
    assert has_open_durable_pause([_ev("plan_review_required", "p1")]) is True


def test_open_pause_false_when_resolved():
    journal = [_ev("checkpoint_required", "c1"), _ev("checkpoint_resolved", "c1")]
    assert has_open_durable_pause(journal) is False


def test_open_pause_false_for_delegation_only():
    # A team graph with no journaled checkpoint (e.g. an approval pause — approvals are
    # transport-only, never journaled) is NOT a durable pause: salvage should cover it.
    journal = [_ev("run_plan"), _ev("run_started"), _ev("run_completed")]
    assert has_open_durable_pause(journal) is False


# --- _salvage_incomplete_turn (spawn decision) ---


@pytest.fixture
def capture(monkeypatch):
    """Patch the persist + spawn seam so the decision is observable without a DB."""
    spawned: list = []
    persist_calls: list[dict] = []

    def fake_persist(**kwargs):
        persist_calls.append(kwargs)
        return MagicMock(name="persist_coro")  # not awaited (spawn is faked)

    def fake_spawn(coro):
        spawned.append(coro)
        return MagicMock(name="task")

    monkeypatch.setattr(turn_persistence, "persist_incomplete_turn", fake_persist)
    monkeypatch.setattr(turn_persistence, "spawn_background", fake_spawn)
    return spawned, persist_calls


def test_salvage_spawns_on_finished_work(monkeypatch, capture):
    spawned, persist_calls = capture
    monkeypatch.setattr(settings, "incomplete_turn_persist_enabled", True)
    journal = [_ev("run_plan"), _ev("run_completed")]
    salvage_incomplete_turn(
        sink=_Sink(journal), conversation_id="conv", trace_id="trace", message_id="m1"
    )
    assert len(spawned) == 1
    assert persist_calls[0]["conversation_id"] == "conv"
    assert persist_calls[0]["trace_id"] == "trace"
    assert persist_calls[0]["journal"] == journal


def test_salvage_skips_when_gate_off(monkeypatch, capture):
    spawned, _ = capture
    monkeypatch.setattr(settings, "incomplete_turn_persist_enabled", False)
    salvage_incomplete_turn(
        sink=_Sink([_ev("run_plan")]), conversation_id="conv", trace_id="trace", message_id="m1"
    )
    assert spawned == []


def test_salvage_skips_when_no_journal_and_no_content(monkeypatch, capture):
    spawned, _ = capture
    monkeypatch.setattr(settings, "incomplete_turn_persist_enabled", True)
    # Nothing streamed and no finished team work ⇒ nothing to keep.
    salvage_incomplete_turn(
        sink=_Sink(None), conversation_id="conv", trace_id="trace", message_id="m1"
    )
    assert spawned == []


def test_salvage_spawns_on_streamed_content_without_journal(monkeypatch, capture):
    # 中途取消 salvage: a pure-text answer (no team/tool journal surface) that was cut off
    # mid-stream must still be kept — the CEO's streamed text is carried through.
    spawned, persist_calls = capture
    monkeypatch.setattr(settings, "incomplete_turn_persist_enabled", True)
    salvage_incomplete_turn(
        sink=_Sink(None, content="已经写了一半的答案"),
        conversation_id="conv",
        trace_id="trace",
        message_id="m1",
    )
    assert len(spawned) == 1
    assert persist_calls[0]["content"] == "已经写了一半的答案"
    assert persist_calls[0]["journal"] == []


def test_salvage_defers_to_resume_on_durable_pause(monkeypatch, capture):
    spawned, _ = capture
    monkeypatch.setattr(settings, "incomplete_turn_persist_enabled", True)
    monkeypatch.setattr(settings, "structured_suspension_persist_enabled", True)
    journal = [_ev("run_plan"), _ev("plan_review_required", "p1")]
    salvage_incomplete_turn(
        sink=_Sink(journal), conversation_id="conv", trace_id="trace", message_id="m1"
    )
    assert spawned == []  # a paused_turns frame owns this turn's continuation


def test_salvage_runs_on_pause_when_persistence_disabled(monkeypatch, capture):
    spawned, _ = capture
    monkeypatch.setattr(settings, "incomplete_turn_persist_enabled", True)
    monkeypatch.setattr(settings, "structured_suspension_persist_enabled", False)
    # No durable frame exists (2a in-memory only) ⇒ salvage the finished work instead.
    journal = [_ev("run_plan"), _ev("plan_review_required", "p1")]
    salvage_incomplete_turn(
        sink=_Sink(journal), conversation_id="conv", trace_id="trace", message_id="m1"
    )
    assert len(spawned) == 1


# --- _persist_incomplete_turn (persisted shape) ---


async def test_persist_incomplete_writes_cancelled_message(monkeypatch):
    updated: dict = {}
    journaled: dict = {}

    class FakeRepo:
        def __init__(self, _session):
            pass

        async def get_by_id(self, mid, conversation_id=None):
            return None

        async def upsert_assistant(self, **kwargs):
            updated.update(kwargs)

    class FakeJournalRepo:
        def __init__(self, _session):
            pass

        async def load_owned(self, turn_id, conversation_id):
            return []

    class FakeSessionCM:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *_a):
            return False

    async def fake_journal(_session, **kwargs):
        journaled.update(kwargs)

    class _Store:
        async def clear_stream_segments(self, *, turn_id):
            pass

    from agentcore.runtime import turn_interrupt as interrupt_mod

    monkeypatch.setattr(interrupt_mod, "MessageRepository", FakeRepo)
    monkeypatch.setattr(interrupt_mod, "TurnJournalRepository", FakeJournalRepo)
    monkeypatch.setattr(interrupt_mod, "async_session_factory", lambda: FakeSessionCM())
    monkeypatch.setattr(interrupt_mod, "persist_turn_journal", fake_journal)
    monkeypatch.setattr(
        "agentcore.conversation.store.get_cloud_store",
        lambda: _Store(),
    )

    journal = [_ev("run_plan"), _ev("run_completed")]
    await persist_incomplete_turn(
        journal=journal, content="", conversation_id="conv", trace_id="trace", message_id="m1"
    )

    assert updated["content"] == ""
    assert "runs" not in updated
    assert updated["metadata"]["status"] == turn_persistence.MESSAGE_STATUS_INCOMPLETE
    assert updated["metadata"]["incomplete"] is True
    assert updated["metadata"]["finish_reason"] == FinishReason.CANCELLED.value
    assert updated["message_id"] == "m1"
    assert updated["trace_id"] == "trace"
    # The cancelled turn's finished team work is recorded to the journal.
    assert journaled["message_id"] == "m1"
    display_entries = [e for e in journaled["entries"] if e["kind"] != "turn_end"]
    assert [e["kind"] for e in display_entries] == ["run_plan", "run_completed"]
    turn_end = next(e for e in journaled["entries"] if e["kind"] == "turn_end")
    assert turn_end["payload"]["finish_reason"] == FinishReason.CANCELLED.value


async def test_persist_incomplete_keeps_streamed_reply(monkeypatch):
    """When the CEO had already streamed a reply, the salvaged message keeps that text
    without appending stop chrome (chrome is metadata + UI)."""
    updated: dict = {}

    class FakeRepo:
        def __init__(self, _session):
            pass

        async def get_by_id(self, mid, conversation_id=None):
            return None

        async def upsert_assistant(self, **kwargs):
            updated.update(kwargs)

    class FakeJournalRepo:
        def __init__(self, _session):
            pass

        async def load_owned(self, turn_id, conversation_id):
            return []

    class FakeSessionCM:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *_a):
            return False

    async def fake_journal(_session, **kwargs):
        pass

    class _Store:
        async def clear_stream_segments(self, *, turn_id):
            pass

    from agentcore.runtime import turn_interrupt as interrupt_mod

    monkeypatch.setattr(interrupt_mod, "MessageRepository", FakeRepo)
    monkeypatch.setattr(interrupt_mod, "TurnJournalRepository", FakeJournalRepo)
    monkeypatch.setattr(interrupt_mod, "async_session_factory", lambda: FakeSessionCM())
    monkeypatch.setattr(interrupt_mod, "persist_turn_journal", fake_journal)
    monkeypatch.setattr(
        "agentcore.conversation.store.get_cloud_store",
        lambda: _Store(),
    )

    await persist_incomplete_turn(
        journal=[],
        content="这是我已经写了一半的分析",
        conversation_id="conv",
        trace_id="trace",
        message_id="m2",
    )
    assert "这是我已经写了一半的分析" in updated["content"]
    assert updated["metadata"]["status"] == turn_persistence.MESSAGE_STATUS_INCOMPLETE
    assert updated["metadata"]["incomplete"] is True
    assert updated["metadata"]["finish_reason"] == FinishReason.CANCELLED.value


async def test_persist_incomplete_swallows_db_errors(monkeypatch):
    class BoomCM:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *_a):
            return False

    from agentcore.runtime import turn_interrupt as interrupt_mod

    monkeypatch.setattr(interrupt_mod, "async_session_factory", lambda: BoomCM())
    # Best-effort (文档铁律): a persistence failure must never escape this task.
    await persist_incomplete_turn(
        journal=[_ev("run_plan")],
        content="",
        conversation_id="conv",
        trace_id="trace",
        message_id="m3",
    )
