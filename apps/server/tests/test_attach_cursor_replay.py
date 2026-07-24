"""P3 precise resume: journal cursor replay + SSE id wiring."""

from __future__ import annotations

import asyncio

from agentcore.api import sse
from agentcore.runtime.events import EventSink, content_delta, tool_use_start
from agentcore.runtime.events.attach_replay import (
    _turn_end_close_event,
    build_cursor_replay,
    journal_rows_to_sse,
    synthesize_segment_deltas,
)
from agentcore.runtime.events.stream_checkpointer import (
    CHANNEL_CAPTAIN_CONTENT,
    CHANNEL_CAPTAIN_REASONING,
    run_output_channel,
)
from agentcore.runtime.events.types import EventType
from agentcore.runtime.journal.writer import TurnJournalWriter, current_journal_writer


def test_journal_rows_to_sse_only_after_cursor_shape():
    """Given rows (already filtered seq > last), emit durable SSE with seq; skip exec."""
    rows = [
        {
            "seq": 2,
            "kind": "tool_use_start",
            "payload": {"tool_call_id": "t1", "tool_name": "web_search", "arguments": {}},
            "ts": "2026-01-01T00:00:00Z",
        },
        {
            "seq": 3,
            "kind": "llm_call",  # EXECUTION_ONLY — skipped
            "payload": {"run_id": "r1"},
            "ts": "2026-01-01T00:00:01Z",
        },
        {
            "seq": 4,
            "kind": "tool_use_end",
            "payload": {
                "tool_call_id": "t1",
                "tool_name": "web_search",
                "status": "success",
                "result": "ok",
            },
            "ts": "2026-01-01T00:00:02Z",
        },
    ]
    events = journal_rows_to_sse(rows)
    assert [e.type for e in events] == [EventType.TOOL_USE_START, EventType.TOOL_USE_END]
    assert [e.seq for e in events] == [2, 4]
    assert events[0].payload["tool_call_id"] == "t1"


def test_journal_rows_splices_message_final_before_terminal():
    rows = [
        {
            "seq": 1,
            "kind": "run_started",
            "payload": {"run_id": "w1", "agent_id": "ag1", "kind": "agent"},
            "ts": "t0",
        },
        {
            "seq": 2,
            "kind": "message_final",
            "payload": {"run_id": "w1", "content": "DONE", "reasoning": "think"},
            "ts": "t1",
        },
        {
            "seq": 3,
            "kind": "run_completed",
            "payload": {"run_id": "w1", "agent_id": "ag1"},
            "ts": "t2",
        },
    ]
    events = journal_rows_to_sse(rows)
    types = [e.type for e in events]
    assert types == [
        EventType.RUN_STARTED,
        EventType.RUN_REASONING_DELTA,
        EventType.RUN_OUTPUT_DELTA,
        EventType.RUN_COMPLETED,
    ]
    assert events[1].seq is None and events[1].payload["delta"] == "think"
    assert events[2].seq is None and events[2].payload["delta"] == "DONE"
    assert events[3].seq == 3


def test_synthesize_segment_deltas_captain_and_worker():
    events = synthesize_segment_deltas(
        by_channel={
            CHANNEL_CAPTAIN_REASONING: "r",
            CHANNEL_CAPTAIN_CONTENT: "hello",
            run_output_channel("w1"): "partial",
        },
        agent_run_ids={"w1": "ag1"},
        covered_run_ids=set(),
    )
    assert [e.type for e in events] == [
        EventType.REASONING_DELTA,
        EventType.CONTENT_DELTA,
        EventType.RUN_OUTPUT_DELTA,
    ]
    assert all(e.seq is None for e in events)
    assert events[1].payload["delta"] == "hello"
    assert events[2].payload["run_id"] == "w1"


def test_synthesize_skips_covered_runs():
    events = synthesize_segment_deltas(
        by_channel={run_output_channel("w1"): "x"},
        agent_run_ids={"w1": "ag1"},
        covered_run_ids={"w1"},
    )
    assert events == []


async def test_durable_emit_stamps_sse_id_from_barrier(monkeypatch):
    """append-on-emit barrier resolves with seq → ``id:`` on the live frame."""
    allocated = {"n": 0}

    class Store:
        async def append_journal(self, **kwargs) -> int | None:
            allocated["n"] += 1
            return allocated["n"]

    store = Store()
    monkeypatch.setattr(
        "agentcore.conversation.store.get_conversation_store", lambda: store
    )

    writer = TurnJournalWriter(turn_id="m1", conversation_id="c1", trace_id="t1")
    token = current_journal_writer.set(writer)
    sink = EventSink()
    try:
        sink.emit(tool_use_start("c1", "web_search", {}))
        await writer.flush()
        sink.close()
        frames = [frame async for frame in sse._event_generator(sink, None)]
    finally:
        current_journal_writer.reset(token)

    durable = [f for f in frames if "tool_use_start" in f]
    assert len(durable) == 1
    assert "\nid: 1\n" in durable[0]


async def test_ephemeral_delta_has_no_id_line():
    sink = EventSink()
    sink.emit(content_delta("hi"))
    sink.close()
    frames = [frame async for frame in sse._event_generator(sink, None)]
    assert any("content_delta" in f for f in frames)
    assert all("\nid: " not in f for f in frames if "content_delta" in f)


async def test_attach_cursor_path_replays_full_journal_then_segments(monkeypatch):
    """Last-Event-ID path: full-turn journal (incl. process_*) ; no _history content.

    Structured turns do not stitch 旁白 from flat segments. Header value is
    observational — load_after is called with -1 (turn start).
    """
    sink = EventSink()
    sink._message_id = "m1"
    # History would have this if take_over were used — cursor path must NOT replay it.
    sink.emit(content_delta("FROM_HISTORY"))
    sink.detach()

    rows = [
        {
            "seq": 1,
            "kind": "process_content",
            "payload": {"kind": "content", "text": "FROM_PROCESS"},
            "ts": "t0",
        },
        {
            "seq": 2,
            "kind": "tool_use_start",
            "payload": {"tool_call_id": "t1", "tool_name": "web_search", "arguments": {}},
            "ts": "t0",
        },
        {
            "seq": 5,
            "kind": "tool_use_end",
            "payload": {
                "tool_call_id": "t1",
                "tool_name": "web_search",
                "status": "success",
                "result": "ok",
            },
            "ts": "t1",
        },
    ]
    loaded_after: list[int] = []

    class Repo:
        def __init__(self, session: object) -> None:
            pass

        async def load_after(self, turn_id: str, after_seq: int):
            assert turn_id == "m1"
            loaded_after.append(after_seq)
            # Full-turn load ignores the client's cursor (observational only).
            assert after_seq == -1
            return rows

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _Sess())
    monkeypatch.setattr(
        "agentcore.db.repositories.runs.TurnJournalRepository", Repo
    )

    # Flat segment must NOT become a content_delta on structured turns.
    sink.stream_memory_snapshot = (  # type: ignore[method-assign]
        lambda: {CHANNEL_CAPTAIN_CONTENT: "FROM_SEGMENT"}
    )

    gen = sse._attach_generator(sink, last_event_id=4)
    frames: list[str] = []
    try:
        for _ in range(3):
            frames.append(await asyncio.wait_for(gen.__anext__(), timeout=2.0))
    finally:
        await gen.aclose()

    joined = "".join(frames)
    assert loaded_after == [-1]
    assert "FROM_HISTORY" not in joined
    assert "FROM_SEGMENT" not in joined
    assert "FROM_PROCESS" in joined
    # Pre-cursor structure must be present (full replay, not > cursor tail).
    assert "tool_use_start" in joined
    assert "tool_use_end" in joined
    assert "\nid: 1\n" in joined
    assert "\nid: 2\n" in joined
    assert "\nid: 5\n" in joined


# --- 收口事实回放：finished detached turn closes with a synthetic message_end ---
# message_end is DERIVED (never journaled) + a detached turn emits it while detached, so
# a client attaching inside the post-completion persist window would otherwise get no
# close frame and finalize only via the reconnect-banner error salvage. build_cursor_replay
# replays a synthetic message_end whenever the journal carries turn_end (turn finished).


def test_turn_end_close_event_finished_turn_emits_message_end():
    rows = [
        {"seq": 1, "kind": "process_content", "payload": {"kind": "content", "text": "CEO 总结"}},
        {"kind": "turn_end", "payload": {"finish_reason": "end_turn"}, "ts": None},
    ]
    ev = _turn_end_close_event(rows)
    assert ev is not None
    assert ev.type == EventType.MESSAGE_END
    assert ev.payload == {"finish_reason": "end_turn"}


def test_turn_end_close_event_paused_preserves_reason():
    """paused must survive so the client routes to the durable resume card, not complete."""
    ev = _turn_end_close_event([{"kind": "turn_end", "payload": {"finish_reason": "paused"}}])
    assert ev is not None
    assert ev.payload["finish_reason"] == "paused"


def test_turn_end_close_event_running_turn_returns_none():
    """No turn_end yet (turn still running) → None so the live tail delivers the real end."""
    rows = [
        {"seq": 1, "kind": "process_content", "payload": {"kind": "content", "text": "x"}},
    ]
    assert _turn_end_close_event(rows) is None


def test_turn_end_close_event_unknown_reason_falls_back_to_end_turn():
    ev = _turn_end_close_event([{"kind": "turn_end", "payload": {"finish_reason": "??"}}])
    assert ev is not None
    assert ev.payload["finish_reason"] == "end_turn"


def _patch_journal_repo(monkeypatch, rows: list[dict]) -> None:
    class Repo:
        def __init__(self, session: object) -> None:
            pass

        async def load_after(self, turn_id: str, after_seq: int):
            return rows

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class Store:
        async def list_stream_segments(self, *, turn_id: str):
            return []

    monkeypatch.setattr("agentcore.db.base.telemetry_session_factory", lambda: _Sess())
    monkeypatch.setattr("agentcore.db.repositories.runs.TurnJournalRepository", Repo)
    monkeypatch.setattr(
        "agentcore.conversation.store.get_conversation_store", lambda: Store()
    )


async def test_build_cursor_replay_appends_message_end_for_finished_turn(monkeypatch):
    """Finished detached turn: the CEO summary content_delta is followed by a message_end
    close so the attaching client finalizes the bubble instead of the reconnect salvage."""
    rows = [
        {"seq": 1, "kind": "process_content", "payload": {"kind": "content", "text": "CEO 总结"}, "ts": "t0"},
        {"kind": "turn_end", "payload": {"finish_reason": "end_turn"}, "ts": None},
    ]
    _patch_journal_repo(monkeypatch, rows)

    events = await build_cursor_replay(
        turn_id="m1", after_seq=-1, memory_channels={}, memory_agent_ids={}
    )

    assert events[-1].type == EventType.MESSAGE_END
    assert events[-1].payload["finish_reason"] == "end_turn"
    # The summary is still replayed as content before the close frame.
    summary = [
        e for e in events
        if e.type == EventType.CONTENT_DELTA and "CEO 总结" in (e.payload.get("delta") or "")
    ]
    assert len(summary) == 1


async def test_build_cursor_replay_no_close_for_running_turn(monkeypatch):
    """Still-running turn (no turn_end): no synthetic close — the live tail owns the end."""
    rows = [
        {"seq": 1, "kind": "process_content", "payload": {"kind": "content", "text": "进行中"}, "ts": "t0"},
    ]
    _patch_journal_repo(monkeypatch, rows)

    events = await build_cursor_replay(
        turn_id="m1", after_seq=-1, memory_channels={}, memory_agent_ids={}
    )

    assert all(e.type != EventType.MESSAGE_END for e in events)
