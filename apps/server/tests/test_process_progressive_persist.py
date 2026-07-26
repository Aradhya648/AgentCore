"""Process-lane progressive persistence + attach replay (mid-run refresh)."""

from __future__ import annotations

from agentcore.conversation.store.merge import MESSAGE_STATUS_RUNNING
from agentcore.conversation.store.overlay import overlay_message_fields
from agentcore.runtime.events import (
    EventSink,
    FinishReason,
    content_delta,
    reasoning_delta,
    run_output_delta,
    run_reasoning_delta,
    tool_use_end,
    tool_use_start,
)
from agentcore.runtime.events.attach_replay import journal_rows_to_sse, synthesize_segment_deltas
from agentcore.runtime.events.stream_checkpointer import CHANNEL_CAPTAIN_CONTENT
from agentcore.runtime.events.types import EventType
from agentcore.runtime.facts import TurnFactLog, current_fact_log
from agentcore.runtime.pipeline.finalize import _journal_entries_for_turn


def test_sink_persists_closed_content_before_tool():
    """tool_use_start closes the open content step → process_content in fact_log."""
    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(content_delta("## 旁白\n先介绍。"))
        sink.emit(tool_use_start("tc1", "web_search", {"query": "x"}))
        kinds = [e["kind"] for e in log.entries()]
        assert "process_content" in kinds
        content_facts = [e for e in log.entries() if e["kind"] == "process_content"]
        assert content_facts[0]["payload"]["text"] == "## 旁白\n先介绍。"
        # Tool still running — not journaled until tool_use_end.
        assert "process_tool" not in kinds
        sink.emit(
            tool_use_end("tc1", "web_search", success=True, output="ok")
        )
        kinds2 = [e["kind"] for e in log.entries()]
        assert "process_tool" in kinds2
        tool = next(e for e in log.entries() if e["kind"] == "process_tool")
        assert tool["payload"]["status"] == "success"
        assert tool["payload"]["result"] == "ok"
    finally:
        current_fact_log.reset(token)


def test_sink_persists_run_process_symmetrically():
    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(run_reasoning_delta("r1", "w1", "先想。"))
        sink.emit(tool_use_start("tc1", "web_search", {"query": "q"}, run_id="r1"))
        kinds = [e["kind"] for e in log.entries()]
        assert "run_process_reasoning" in kinds
        assert "run_process_tool" not in kinds
        sink.emit(
            tool_use_end("tc1", "web_search", success=True, output="hit", run_id="r1")
        )
        sink.emit(run_output_delta("r1", "w1", "结论。"))
        sink.flush_process_to_journal()
        kinds2 = [e["kind"] for e in log.entries()]
        assert "run_process_tool" in kinds2
        assert "run_process_content" in kinds2
    finally:
        current_fact_log.reset(token)


def test_finalize_only_appends_turn_end_when_process_already_in_log():
    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(content_delta("旁白"))
        sink.emit(tool_use_start("tc1", "web_search", {"query": "x"}))
        sink.emit(tool_use_end("tc1", "web_search", success=True, output="ok"))
        sink.emit(content_delta("交付"))
        # Surface the journal so _should_persist_journal passes.
        sink.seed_journal(
            [{"type": "tool_use_start", "payload": {"tool_call_id": "tc1"}, "timestamp": "t0"}]
        )
        before = len(log.entries())
        durable = _journal_entries_for_turn(log, sink=sink, finish=FinishReason.END_TURN)
        assert durable is not None
        assert durable[-1]["kind"] == "turn_end"
        # No second full process dump — process_* count did not double.
        process_kinds = [e["kind"] for e in durable if e["kind"].startswith("process_")]
        assert process_kinds.count("process_content") == 2  # 旁白 + 交付 (flushed tail)
        assert process_kinds.count("process_tool") == 1
        # Flush may add the open trailing content; only turn_end is the finalize-only append.
        assert durable[-1] == {
            "kind": "turn_end",
            "payload": {"finish_reason": "end_turn"},
            "ts": None,
        }
        assert len(durable) >= before + 1
    finally:
        current_fact_log.reset(token)


def test_journal_rows_to_sse_interleaves_process_with_tools():
    """Attach replay: process_content before tool_use_start, not after all DURABLE."""
    rows = [
        {
            "seq": 1,
            "kind": "process_content",
            "payload": {"kind": "content", "text": "旁白"},
            "ts": "t0",
        },
        {
            "seq": 2,
            "kind": "tool_use_start",
            "payload": {"tool_call_id": "t1", "tool_name": "web_search", "arguments": {}},
            "ts": "t1",
        },
        {
            "seq": 3,
            "kind": "tool_use_end",
            "payload": {
                "tool_call_id": "t1",
                "tool_name": "web_search",
                "status": "success",
                "result": "ok",
            },
            "ts": "t2",
        },
        {
            "seq": 4,
            "kind": "process_content",
            "payload": {"kind": "content", "text": "交付"},
            "ts": "t3",
        },
        {
            "seq": 5,
            "kind": "process_tool",
            "payload": {
                "kind": "tool",
                "id": "t1",
                "tool_name": "web_search",
                "status": "success",
                "result": "ok",
            },
            "ts": "t4",
        },
    ]
    events = journal_rows_to_sse(rows)
    types = [e.type for e in events]
    assert types == [
        EventType.CONTENT_DELTA,
        EventType.TOOL_USE_START,
        EventType.TOOL_USE_END,
        EventType.CONTENT_DELTA,
    ]
    assert events[0].payload["delta"] == "旁白"
    assert events[0].seq == 1
    assert events[3].payload["delta"] == "交付"


def test_journal_rows_to_sse_run_process_interleave():
    rows = [
        {
            "seq": 1,
            "kind": "run_started",
            "payload": {"run_id": "r1", "agent_id": "w1", "kind": "agent"},
            "ts": "t0",
        },
        {
            "seq": 2,
            "kind": "run_process_reasoning",
            "payload": {"run_id": "r1", "kind": "reasoning", "text": "想"},
            "ts": "t1",
        },
        {
            "seq": 3,
            "kind": "tool_use_start",
            "payload": {
                "tool_call_id": "t1",
                "tool_name": "web_search",
                "arguments": {},
                "run_id": "r1",
            },
            "ts": "t2",
        },
        {
            "seq": 4,
            "kind": "run_process_content",
            "payload": {"run_id": "r1", "kind": "content", "text": "结论"},
            "ts": "t3",
        },
    ]
    events = journal_rows_to_sse(rows)
    types = [e.type for e in events]
    assert types == [
        EventType.RUN_STARTED,
        EventType.RUN_REASONING_DELTA,
        EventType.TOOL_USE_START,
        EventType.RUN_OUTPUT_DELTA,
    ]
    assert events[1].payload["delta"] == "想"
    assert events[1].payload["agent_id"] == "w1"


def test_synthesize_skips_captain_when_journal_has_process():
    events = synthesize_segment_deltas(
        by_channel={CHANNEL_CAPTAIN_CONTENT: "FROM_SEGMENT"},
        agent_run_ids={},
        covered_run_ids=set(),
        skip_captain_content=True,
    )
    assert events == []


def test_overlay_skips_captain_content_when_process_present():
    content, reasoning = overlay_message_fields(
        content="",
        reasoning_content=None,
        segments=[{"channel": CHANNEL_CAPTAIN_CONTENT, "text": "旁白不该进 content"}],
        usage={"status": MESSAGE_STATUS_RUNNING},
        skip_captain_content=True,
    )
    assert content == ""
    # Without skip, narration would pour in:
    content2, _ = overlay_message_fields(
        content="",
        reasoning_content=None,
        segments=[{"channel": CHANNEL_CAPTAIN_CONTENT, "text": "旁白不该进 content"}],
        usage={"status": MESSAGE_STATUS_RUNNING},
        skip_captain_content=False,
    )
    assert content2 == "旁白不该进 content"


def test_seed_process_skips_rewriting_on_flush():
    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.seed_process([{"kind": "content", "text": "pre"}])
        sink.emit(reasoning_delta("post"))
        sink.flush_process_to_journal()
        kinds = [e["kind"] for e in log.entries()]
        # Seeded content not re-appended; only live reasoning.
        assert kinds == ["process_reasoning"]
        assert log.entries()[0]["payload"]["text"] == "post"
    finally:
        current_fact_log.reset(token)


def test_content_reset_does_not_journal_discarded_open_content():
    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        from agentcore.runtime.events import content_reset

        sink.emit(content_delta("将被丢弃"))
        # Still open — not persisted yet.
        assert log.entries() == []
        sink.emit(content_reset("finish_guard"))
        sink.flush_process_to_journal()
        assert log.entries() == []
    finally:
        current_fact_log.reset(token)


def test_process_content_journals_before_tool_use_start():
    """Emit order: closed process_* must precede the DURABLE that closed it."""
    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(content_delta("## 旁白"))
        sink.emit(tool_use_start("tc1", "web_search", {"query": "x"}))
        kinds = [e["kind"] for e in log.entries()]
        assert kinds.index("process_content") < kinds.index("tool_use_start")
    finally:
        current_fact_log.reset(token)


def test_structured_journal_skips_segment_narration_fallback():
    """Ratchet: structured turns must not stitch 旁白 from captain:content segments."""
    from agentcore.runtime.events.attach_replay import (
        journal_is_structured,
        synthesize_segment_deltas,
    )

    rows = [
        {
            "seq": 1,
            "kind": "tool_use_start",
            "payload": {"tool_call_id": "t1", "tool_name": "web_search", "arguments": {}},
            "ts": "t0",
        }
    ]
    assert journal_is_structured(rows)
    # No process_* yet (legacy / pre-boundary) — still must not pour segments.
    events = synthesize_segment_deltas(
        by_channel={CHANNEL_CAPTAIN_CONTENT: "旁白不应从 segment 拼回"},
        agent_run_ids={},
        covered_run_ids=set(),
        skip_captain_content=True,
    )
    assert events == []


def test_prose_only_journal_keeps_segment_accelerate():
    from agentcore.runtime.events.attach_replay import journal_is_structured

    rows = [
        {"seq": 1, "kind": "turn_started", "payload": {"user_message": "hi"}, "ts": None},
    ]
    assert not journal_is_structured(rows)


_WEB_SEARCH_DISPLAY = {
    "query": "LV诉茉莉奶白商标侵权",
    "results": [
        {
            "title": "一审判决",
            "url": "https://example.com/lv",
            "snippet": "赔偿相关报道",
            "site": "example.com",
        }
    ],
}


def test_flush_while_tool_running_then_end_journals_terminal_display():
    """flush during a running tool must not pin ``status=running``; tool_use_end wins.

    Regression for cold-reload skeleton: an early flush that journaled a running
    tool left the ordinal cursor past that step, so tool_use_end's in-memory
    success+display never reached ``runs.process``.
    """
    from agentcore.runtime.journal.fold import runs_from_entries

    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(
            tool_use_start(
                "tc1", "web_search", {"query": "LV诉茉莉奶白商标侵权"}
            )
        )
        # Mid-turn / finalize-style flush while the tool is still open.
        sink.flush_process_to_journal()
        assert not any(e["kind"] == "process_tool" for e in log.entries())

        sink.emit(
            tool_use_end(
                "tc1",
                "web_search",
                success=True,
                output='{"query":"LV诉茉莉奶白商标侵权","results":[…]}',
                display=_WEB_SEARCH_DISPLAY,
            )
        )
        tool_facts = [e for e in log.entries() if e["kind"] == "process_tool"]
        assert len(tool_facts) == 1
        assert tool_facts[0]["payload"]["status"] == "success"
        assert tool_facts[0]["payload"]["display"] == _WEB_SEARCH_DISPLAY

        runs = runs_from_entries(log.entries())
        assert runs is not None
        tools = [s for s in (runs.get("process") or []) if s.get("kind") == "tool"]
        assert len(tools) == 1
        assert tools[0]["status"] == "success"
        assert tools[0]["display"] == _WEB_SEARCH_DISPLAY
        assert tools[0]["result"]
    finally:
        current_fact_log.reset(token)


def test_tool_end_compensates_stale_running_process_tool():
    """If a running tool was already journaled (pre-fix / seed skip), end rewrites cold.

    Appends a terminal ``process_tool``; ``runs_from_entries`` last-wins by tool id
    so reload sees success+display, not the stale running row.
    """
    from agentcore.runtime.events.process_persist import schedule_process_step
    from agentcore.runtime.journal.fold import runs_from_entries

    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(
            tool_use_start(
                "tc1", "web_search", {"query": "LV诉茉莉奶白商标侵权"}
            )
        )
        # Simulate the pre-fix bug: running tool already in the journal + cursor past it.
        running = dict(sink.raw_process()[0])
        assert running["status"] == "running"
        schedule_process_step(running)
        sink._process_cursor.seed_captain(1)

        sink.emit(
            tool_use_end(
                "tc1",
                "web_search",
                success=True,
                output="ok",
                display=_WEB_SEARCH_DISPLAY,
            )
        )
        tool_facts = [e for e in log.entries() if e["kind"] == "process_tool"]
        assert len(tool_facts) == 2
        assert tool_facts[0]["payload"]["status"] == "running"
        assert tool_facts[1]["payload"]["status"] == "success"
        assert tool_facts[1]["payload"]["display"] == _WEB_SEARCH_DISPLAY

        runs = runs_from_entries(log.entries())
        assert runs is not None
        tools = [s for s in (runs.get("process") or []) if s.get("kind") == "tool"]
        assert len(tools) == 1
        assert tools[0]["status"] == "success"
        assert tools[0]["display"] == _WEB_SEARCH_DISPLAY
    finally:
        current_fact_log.reset(token)


def test_flush_while_run_tool_running_then_end_journals_terminal_display():
    """Worker-run lane: same open-tool hold + terminal persist as captain."""
    from agentcore.runtime.journal.fold import runs_from_entries

    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(run_reasoning_delta("r1", "w1", "先想。"))
        sink.emit(
            tool_use_start(
                "tc1", "web_search", {"query": "q"}, run_id="r1"
            )
        )
        sink.flush_process_to_journal()
        assert not any(e["kind"] == "run_process_tool" for e in log.entries())

        sink.emit(
            tool_use_end(
                "tc1",
                "web_search",
                success=True,
                output="hit",
                display=_WEB_SEARCH_DISPLAY,
                run_id="r1",
            )
        )
        tool_facts = [e for e in log.entries() if e["kind"] == "run_process_tool"]
        assert len(tool_facts) == 1
        assert tool_facts[0]["payload"]["status"] == "success"
        assert tool_facts[0]["payload"]["display"] == _WEB_SEARCH_DISPLAY

        runs = runs_from_entries(log.entries())
        assert runs is not None
        lane = (runs.get("run_processes") or {}).get("r1") or []
        tools = [s for s in lane if s.get("kind") == "tool"]
        assert len(tools) == 1
        assert tools[0]["status"] == "success"
        assert tools[0]["display"] == _WEB_SEARCH_DISPLAY
    finally:
        current_fact_log.reset(token)


def test_run_plan_persists_process_team_immediately():
    """First displayable run_plan journals ``process_team`` at emit time (mid-run reload)."""
    from agentcore.runtime.events import run_plan
    from agentcore.runtime.journal.fold import runs_from_entries

    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(content_delta("开场旁白"))
        sink.emit(
            run_plan(
                execution_id="e1",
                plan_type="multi_agent",
                task_summary="t",
                agents=[],
                runs=[],
            )
        )
        # No flush — workers may still be running; journal must already carry team.
        assert "process_team" in [e["kind"] for e in log.entries()]
        team_facts = [e for e in log.entries() if e["kind"] == "process_team"]
        assert len(team_facts) == 1
        assert team_facts[0]["payload"] == {"kind": "team", "execution_id": "e1"}

        sink.emit(content_delta("收束"))
        sink.flush_process_to_journal()
        runs = runs_from_entries(log.entries())
        assert runs is not None
        assert [s["kind"] for s in (runs.get("process") or [])] == [
            "content",
            "team",
            "content",
        ]
        # Same execution again — dedupe, no second process_team.
        sink.emit(
            run_plan(
                execution_id="e1",
                plan_type="multi_agent",
                task_summary="t2",
                agents=[],
                runs=[],
            )
        )
        assert len([e for e in log.entries() if e["kind"] == "process_team"]) == 1
    finally:
        current_fact_log.reset(token)


def test_run_plan_growth_frame_skips_process_team():
    """Cross-turn growth run_plan (host_message_id) must not insert/journal a new team."""
    from agentcore.runtime.events import run_plan

    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(
            run_plan(
                execution_id="e1",
                plan_type="multi_agent",
                task_summary="t",
                agents=[],
                runs=[],
                host_message_id="host-msg-1",
            )
        )
        assert not any(s.get("kind") == "team" for s in sink.raw_process())
        assert "process_team" not in [e["kind"] for e in log.entries()]
    finally:
        current_fact_log.reset(token)


def test_persist_required_marker_keeps_team_preview_before_team():
    """Capture-path team_preview must cold-reload before ``team`` (before_last_team).

    Regression: flush-then-``seed_captain(len)`` pinned ``process_team`` ahead of
    ``process_team_preview`` in journal order, so reopen showed 协作图 before 开工卡.

    ``run_plan`` now journals ``process_team`` immediately; fold still applies
    before_last_team so reload order stays 开工卡 → 协作图.
    """
    from agentcore.runtime.events import run_plan
    from agentcore.runtime.events.types import EventType
    from agentcore.runtime.journal.fold import runs_from_entries

    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(content_delta("开场"))
        sink.emit(
            run_plan(
                execution_id="e1",
                plan_type="team",
                task_summary="t",
                agents=[],
                runs=[],
            )
        )
        # Capture order: marker first, then flush (see turn_paused_capture).
        sink.persist_required_marker(
            EventType.TEAM_PREVIEW_REQUIRED, {"checkpoint_id": "tp1"}
        )
        sink.flush_process_to_journal()

        assert [s["kind"] for s in sink.raw_process()] == [
            "content",
            "team_preview",
            "team",
        ]
        runs = runs_from_entries(log.entries())
        assert runs is not None
        assert [s["kind"] for s in (runs.get("process") or [])] == [
            "content",
            "team_preview",
            "team",
        ]
        # No duplicate process_team from mid-insert compensation.
        assert len([e for e in log.entries() if e["kind"] == "process_team"]) == 1
        assert len([e for e in log.entries() if e["kind"] == "process_team_preview"]) == 1
    finally:
        current_fact_log.reset(token)


def test_persist_required_marker_after_open_tool_still_journals_checkpoint():
    """SUSPEND ask_user leaves a running tool; pause marker must still land in process_*."""
    from agentcore.runtime.events.types import EventType
    from agentcore.runtime.journal.fold import runs_from_entries

    log = TurnFactLog()
    token = current_fact_log.set(log)
    sink = EventSink()
    try:
        sink.emit(content_delta("问之前"))
        sink.emit(tool_use_start("tc1", "ask_user", {"message": "继续吗?"}))
        sink.persist_required_marker(
            EventType.CHECKPOINT_REQUIRED, {"checkpoint_id": "cp1"}
        )
        sink.flush_process_to_journal()

        runs = runs_from_entries(log.entries())
        assert runs is not None
        kinds = [s["kind"] for s in (runs.get("process") or [])]
        assert kinds == ["content", "checkpoint"]
        assert "process_checkpoint" in [e["kind"] for e in log.entries()]
    finally:
        current_fact_log.reset(token)


def test_runs_from_entries_synthesizes_team_when_process_team_missing():
    """Legacy journals: run_plan + later process_content, no process_team → team before 终稿."""
    from agentcore.runtime.journal.fold import runs_from_entries

    entries = [
        {
            "kind": "run_plan",
            "payload": {
                "execution_id": "e-legacy",
                "plan_type": "multi_agent",
                "task_summary": "t",
                "agents": [],
                "runs": [],
            },
            "ts": "2026-01-01T00:00:00Z",
        },
        {
            "kind": "process_content",
            "payload": {"kind": "content", "text": "进展。"},
            "ts": "2026-01-01T00:00:01Z",
        },
        {
            "kind": "process_content",
            "payload": {"kind": "content", "text": "终稿。"},
            "ts": "2026-01-01T00:00:02Z",
        },
    ]
    runs = runs_from_entries(entries)
    assert runs is not None
    assert [s["kind"] for s in (runs.get("process") or [])] == [
        "team",
        "content",
        "content",
    ]
    assert (runs["process"][0].get("execution_id")) == "e-legacy"
    # Growth frame must not invent a team on the appending turn.
    growth = [
        {
            "kind": "run_plan",
            "payload": {
                "execution_id": "e-legacy",
                "host_message_id": "m-host",
                "plan_type": "multi_agent",
                "task_summary": "t",
                "agents": [],
                "runs": [],
            },
            "ts": "2026-01-01T00:00:00Z",
        },
        {
            "kind": "process_content",
            "payload": {"kind": "content", "text": "追加旁白。"},
            "ts": "2026-01-01T00:00:01Z",
        },
    ]
    growth_runs = runs_from_entries(growth)
    assert growth_runs is not None
    assert [s["kind"] for s in (growth_runs.get("process") or [])] == ["content"]
