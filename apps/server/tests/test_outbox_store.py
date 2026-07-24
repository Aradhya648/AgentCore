"""OutboxStore progressive write + idempotency tests (as-built: 双模式工作区 §10.3)."""

from __future__ import annotations

import asyncio
import json

import pytest

from agentcore.conversation.store import reset_conversation_store_for_tests
from agentcore.conversation.store.outbox import (
    PHASE_OPEN,
    PHASE_READY,
    OutboxStore,
    captain_text_from_stream_segments,
    list_outbox_records,
    to_record_turn_body,
)


@pytest.fixture(autouse=True)
def _reset_conversation_store():
    yield
    reset_conversation_store_for_tests()


def _drive(coro):
    return asyncio.run(coro)


def test_progressive_begin_checkpoint_finalize(tmp_path):
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hello",
        message_id="m1",
        trace_id="a" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="a" * 32)
        await store.checkpoint(conversation_id="c1", message_id="m1", content="Hel")
        await store.checkpoint(conversation_id="c1", message_id="m1", content="Hello")
        # Shorter checkpoint must not shrink (monotonic).
        await store.checkpoint(conversation_id="c1", message_id="m1", content="He")
        await store.append_journal(
            turn_id="m1",
            seq=0,
            conversation_id="c1",
            trace_id="a" * 32,
            entry={"kind": "run_started", "payload": {}},
        )
        await store.append_journal(
            turn_id="m1",
            seq=0,  # duplicate seq — ignored
            conversation_id="c1",
            trace_id="a" * 32,
            entry={"kind": "SHOULD_NOT_REPLACE", "payload": {}},
        )
        await store.finalize(
            mode="local",
            conversation_id="c1",
            user_message="hello",
            user_message_id="u1",
            assistant_content="Hello world",
            message_id="m1",
            trace_id="a" * 32,
            finish_reason="stop",
            input_tokens=3,
            output_tokens=2,
            runs={"events": []},
        )
        # Second finalize is a no-op seal.
        await store.finalize(
            mode="local",
            conversation_id="c1",
            user_message="hello",
            user_message_id="u1",
            assistant_content="SHORTER",
            message_id="m1",
            trace_id="a" * 32,
            finish_reason="stop",
        )
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["phase"] == PHASE_READY
    assert record["content"] == "Hello world"
    assert record["journal"] == {"0": {"kind": "run_started", "payload": {}}}
    assert record["ops"][0] == "begin_turn"
    assert "finalize" in record["ops"]
    body = to_record_turn_body(record)
    assert body["user_message_id"] == "u1"
    assert body["content"] == "Hello world"
    assert body["input_tokens"] == 3


def test_finalize_complete_overrides_longer_checkpoint(tmp_path):
    """Happy-path finalize may replace a longer mid-stream checkpoint body."""
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="f" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="f" * 32)
        await store.checkpoint(
            conversation_id="c1",
            message_id="m1",
            content="a long mid-stream draft that spilled past the final",
        )
        await store.finalize(
            conversation_id="c1",
            user_message="hi",
            assistant_content="final",
            user_message_id="u1",
            message_id="m1",
            trace_id="f" * 32,
            finish_reason="end_turn",
        )
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["content"] == "final"


def test_begin_turn_idempotent(tmp_path):
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="b" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="b" * 32)
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="b" * 32)
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["ops"].count("begin_turn") == 1


def test_salvage_retains_open_when_settlement_has_resume_frame(tmp_path):
    """D2 retain-open: settled but non-terminal → do not salvage→ready."""
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="f" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="f" * 32)
        await store.append_journal(
            turn_id="m1",
            seq=0,
            conversation_id="c1",
            trace_id="f" * 32,
            entry={
                "kind": "team_preview_resolved",
                "payload": {
                    "checkpoint_id": "tp1",
                    "decision": "continue",
                    "resume_frame": {"frame": {"kind": "team_preview"}},
                },
                "ts": None,
            },
        )
        await store.checkpoint(conversation_id="c1", message_id="m1", content="partial")
        await store.salvage(
            journal=[],
            content="partial+",
            conversation_id="c1",
            trace_id="f" * 32,
            message_id="m1",
        )
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["phase"] == PHASE_OPEN
    assert "salvage_retain_open" in record["ops"]
    assert "salvage" not in record["ops"]
    assert record.get("finish_reason") in (None, "")


def test_salvage_retains_open_even_when_later_gate_pending(tmp_path):
    """Conservative retain: settlement wins even if a later cold gate is pending."""
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="h" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="h" * 32)
        await store.append_journal(
            turn_id="m1",
            seq=0,
            conversation_id="c1",
            trace_id="h" * 32,
            entry={
                "kind": "team_preview_resolved",
                "payload": {
                    "checkpoint_id": "tp1",
                    "decision": "continue",
                    "resume_frame": {"frame": {"kind": "team_preview"}},
                },
                "ts": None,
            },
        )
        await store.append_journal(
            turn_id="m1",
            seq=1,
            conversation_id="c1",
            trace_id="h" * 32,
            entry={
                "kind": "checkpoint_required",
                "payload": {"checkpoint_id": "cp2"},
                "ts": None,
            },
        )
        await store.salvage(
            journal=[],
            content="partial",
            conversation_id="c1",
            trace_id="h" * 32,
            message_id="m1",
        )
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["phase"] == PHASE_OPEN
    assert "salvage_retain_open" in record["ops"]


def test_salvage_marks_ready(tmp_path):
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="c" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="c" * 32)
        await store.checkpoint(conversation_id="c1", message_id="m1", content="partial")
        await store.salvage(
            journal=[{"kind": "x"}],
            content="partial+",
            conversation_id="c1",
            trace_id="c" * 32,
            message_id="m1",
        )
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["phase"] == PHASE_READY
    assert record["content"] == "partial+"
    assert record["finish_reason"] == "cancelled"
    assert "salvage" in record["ops"]
    body = to_record_turn_body(record)
    assert body["finish_reason"] == "cancelled"
    assert body["journal"] == [{"kind": "x"}]


def test_to_record_turn_body_includes_sorted_journal(tmp_path):
    """Crash salvage: runs=None but journal map must ride the write-back body."""
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="e" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="e" * 32)
        await store.append_journal(
            turn_id="m1",
            seq=2,
            conversation_id="c1",
            trace_id="e" * 32,
            entry={"kind": "run_completed", "payload": {"id": "r1"}, "ts": None},
        )
        await store.append_journal(
            turn_id="m1",
            seq=0,
            conversation_id="c1",
            trace_id="e" * 32,
            entry={"kind": "run_started", "payload": {"id": "r1"}, "ts": "t0"},
        )
        await store.checkpoint(conversation_id="c1", message_id="m1", content="partial")
        await store.salvage(
            journal=[],
            content="partial",
            conversation_id="c1",
            trace_id="e" * 32,
            message_id="m1",
        )
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["runs"] is None
    body = to_record_turn_body(record)
    assert "runs" in body
    assert body["runs"] is None
    assert body["journal"] == [
        {"kind": "run_started", "payload": {"id": "r1"}, "ts": "t0"},
        {"kind": "run_completed", "payload": {"id": "r1"}, "ts": None},
    ]
    assert body["finish_reason"] == "cancelled"


def test_list_outbox_records(tmp_path):
    base = tmp_path / "outbox"
    store = OutboxStore(base)
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="a",
        message_id="m1",
        trace_id="d" * 32,
    )
    _drive(store.begin_turn(conversation_id="c1", message_id="m1", trace_id="d" * 32))
    (base / "torn.json").write_text("{", encoding="utf-8")
    records = list_outbox_records(base)
    assert len(records) == 1
    assert records[0]["user_message_id"] == "u1"


def test_stream_segments_survive_hard_kill_without_salvage(tmp_path):
    """D6: StreamCheckpointer flush lands on disk; hard-kill skips salvage but snapshots remain."""
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hello",
        message_id="m1",
        trace_id="g" * 32,
    )

    async def run() -> None:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="g" * 32)
        await store.upsert_stream_segments(
            turn_id="m1",
            segments=[
                ("captain:content", "half-written reply", 0),
                ("captain:reasoning", "thinking…", 0),
            ],
        )
        # Simulate hard-kill: no salvage / finalize / clear_turn — just drop the process.
        # (ctx stays bound here; the durable proof is the file on disk.)

    _drive(run())
    path = tmp_path / "outbox" / "u1.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["phase"] == "open"
    assert (record.get("content") or "") == ""
    assert record["stream_segments"]["captain:content"] == {
        "text": "half-written reply",
        "generation": 0,
    }
    assert record["stream_segments"]["captain:reasoning"] == {
        "text": "thinking…",
        "generation": 0,
    }
    content, reasoning = captain_text_from_stream_segments(record["stream_segments"])
    assert content == "half-written reply"
    assert reasoning == "thinking…"
    assert "stream_segments" in record["ops"]
    # Read-side overlay stays out of scope for local outbox.
    assert _drive(store.list_stream_segments(turn_id="m1")) == []


def test_stream_segments_monotonic_and_ready_sealed(tmp_path):
    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="h" * 32,
    )

    async def run() -> dict:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="h" * 32)
        await store.upsert_stream_segments(
            turn_id="m1",
            segments=[("captain:content", "hello", 0)],
        )
        # Same-gen shorter must not shrink.
        await store.upsert_stream_segments(
            turn_id="m1",
            segments=[("captain:content", "he", 0)],
        )
        await store.upsert_stream_segments(
            turn_id="m1",
            segments=[("captain:content", "hello world", 0)],
        )
        await store.finalize(
            conversation_id="c1",
            user_message="hi",
            user_message_id="u1",
            assistant_content="final",
            message_id="m1",
            trace_id="h" * 32,
            finish_reason="stop",
        )
        # Sealed ready: further stream upserts ignored.
        await store.upsert_stream_segments(
            turn_id="m1",
            segments=[("captain:content", "should not land", 1)],
        )
        return json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))

    record = _drive(run())
    assert record["content"] == "final"
    assert record["stream_segments"]["captain:content"]["text"] == "hello world"
    assert record["phase"] == PHASE_READY


def test_outbox_process_journal_visible_at_semantic_boundary(tmp_path):
    """Local mid-run: process_* lands in outbox before finalize (D6 / attach isomorphic)."""
    from agentcore.conversation.store import set_conversation_store
    from agentcore.conversation.store.outbox import journal_entries_from_map
    from agentcore.runtime.events import EventSink, content_delta, tool_use_start
    from agentcore.runtime.facts import TurnFactLog, current_fact_log
    from agentcore.runtime.journal.writer import TurnJournalWriter, current_journal_writer

    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="j" * 32,
    )
    set_conversation_store(store)

    async def run() -> None:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="j" * 32)
        log = TurnFactLog()
        fl = current_fact_log.set(log)
        writer = TurnJournalWriter(
            turn_id="m1", conversation_id="c1", trace_id="j" * 32
        )
        wt = current_journal_writer.set(writer)
        sink = EventSink()
        try:
            sink.emit(content_delta("## 旁白\n本地可见。"))
            sink.emit(tool_use_start("tc1", "web_search", {"query": "q"}))
            # Drain SSE barriers so journal writes complete before we read the file.
            while True:
                ev = await sink.get()
                if ev is None:
                    break
                if ev.type.value == "tool_use_start":
                    sink.close()
            await writer.flush()
        finally:
            current_journal_writer.reset(wt)
            current_fact_log.reset(fl)

        record = store.find_record_by_message_id("m1")
        assert record is not None
        assert record["phase"] == "open"
        entries = journal_entries_from_map(record.get("journal")) or []
        kinds = [e.get("kind") for e in entries]
        assert "process_content" in kinds
        assert "tool_use_start" in kinds
        assert kinds.index("process_content") < kinds.index("tool_use_start")

    _drive(run())


def test_write_retries_transient_replace_lock(tmp_path, monkeypatch):
    """Windows WinError 5 / sharing violation: retry replace, then succeed."""
    import agentcore.conversation.store.outbox as outbox_mod

    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="r" * 32,
    )
    calls = {"n": 0}
    real_replace = outbox_mod.os.replace

    def flaky(src, dst):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] < 3:
            err = OSError(5, "Access is denied")
            err.winerror = 5  # type: ignore[attr-defined]
            raise err
        real_replace(src, dst)

    monkeypatch.setattr(outbox_mod.os, "replace", flaky)
    monkeypatch.setattr(outbox_mod, "_REPLACE_RETRY_DELAYS_S", (0.0, 0.0, 0.0, 0.0, 0.0))

    async def run() -> None:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="r" * 32)

    _drive(run())
    assert calls["n"] == 3
    record = json.loads((tmp_path / "outbox" / "u1.json").read_text(encoding="utf-8"))
    assert record["phase"] == PHASE_OPEN
    assert "begin_turn" in record["ops"]


def test_write_logs_failure_after_exhausted_replace_retries(tmp_path, monkeypatch):
    """Exhausted transient locks still surface ``sidecar.outbox_write_failed``."""
    import agentcore.conversation.store.outbox as outbox_mod

    store = OutboxStore(tmp_path / "outbox")
    store.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="hi",
        message_id="m1",
        trace_id="f" * 32,
    )
    errors: list[tuple] = []

    def always_locked(src, dst):  # noqa: ANN001
        del src, dst
        err = OSError(5, "Access is denied")
        err.winerror = 5  # type: ignore[attr-defined]
        raise err

    class _Spy:
        def error(self, event, **kwargs):  # noqa: ANN001
            errors.append((event, kwargs))

        def warning(self, event, **kwargs):  # noqa: ANN001
            pass

    monkeypatch.setattr(outbox_mod.os, "replace", always_locked)
    monkeypatch.setattr(outbox_mod, "_REPLACE_RETRY_DELAYS_S", (0.0, 0.0))
    monkeypatch.setattr(outbox_mod, "logger", _Spy())

    async def run() -> None:
        await store.begin_turn(conversation_id="c1", message_id="m1", trace_id="f" * 32)

    _drive(run())  # must not raise into the turn
    assert errors and errors[0][0] == "sidecar.outbox_write_failed"
    assert not (tmp_path / "outbox" / "u1.json").exists()

