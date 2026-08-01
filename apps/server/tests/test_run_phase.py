"""Backend unit tests for worker ``run_phase`` (activity phase) wire + projection."""

from __future__ import annotations

from agentcore.conformance.export import _serialize_events
from agentcore.conformance.projection import project_turn
from agentcore.conformance.vectors.multi_agent.run_phase import _multi_agent_run_phase
from agentcore.runtime.events import run_phase, run_plan, run_started
from agentcore.runtime.events.disposition import EVENT_DISPOSITION, Disposition
from agentcore.runtime.events.types import EventType
from agentcore.runtime.runs.run_phase_emit import emit_run_phase


def test_run_phase_event_type_and_disposition():
    assert EventType.RUN_PHASE.value == "run_phase"
    disposition, _reason = EVENT_DISPOSITION[EventType.RUN_PHASE]
    assert disposition is Disposition.EPHEMERAL


def test_run_phase_factory_tool_name_only_for_tool():
    thinking = run_phase("r1", "w1", "thinking")
    assert thinking.payload == {
        "run_id": "r1",
        "agent_id": "w1",
        "phase": "thinking",
    }
    tool = run_phase("r1", "w1", "tool", tool_name="file_read")
    assert tool.payload["tool_name"] == "file_read"
    waiting = run_phase("r1", "w1", "waiting_children", tool_name="ignored")
    assert "tool_name" not in waiting.payload


def test_emit_run_phase_noop_without_sink_or_run_id():
    class _Sink:
        def __init__(self) -> None:
            self.events = []

        def emit(self, ev) -> None:  # noqa: ANN001
            self.events.append(ev)

    sink = _Sink()
    emit_run_phase(None, "r1", "w1", "thinking")
    emit_run_phase(sink, "", "w1", "thinking")
    assert sink.events == []
    emit_run_phase(sink, "r1", "w1", "winding_down")
    assert len(sink.events) == 1
    assert sink.events[0].type is EventType.RUN_PHASE
    assert sink.events[0].payload["phase"] == "winding_down"


def test_projection_run_phase_sticky_winding_down_and_status_sides():
    projected = project_turn(_serialize_events(_multi_agent_run_phase()))
    by_id = {r["id"]: r for r in projected["runs"]}
    assert by_id["r1"]["status"] == "running"
    assert by_id["r1"]["phase"] == "winding_down"
    assert by_id["r1"].get("phaseTool") is None
    # queued = pending status (no phase field required)
    assert by_id["r2"]["status"] == "pending"
    assert "phase" not in by_id["r2"]
    # skipped = skipped status
    assert by_id["r3"]["status"] == "skipped"
    assert "phase" not in by_id["r3"]


def test_projection_tool_phase_carries_tool_name():
    from agentcore.runtime.events import message_start

    events = _serialize_events(
        [
            message_start("m1", conversation_id="c1"),
            run_plan(
                execution_id="e1",
                plan_type="multi_agent",
                task_summary="t",
                agents=[{"id": "w1", "role": "工程师", "thinking": True}],
                runs=[{"id": "r1", "agent_id": "w1", "task": "x", "depends_on": []}],
            ),
            run_started("r1", "w1"),
            run_phase("r1", "w1", "tool", tool_name="grep"),
        ]
    )
    projected = project_turn(events)
    run = next(r for r in projected["runs"] if r["id"] == "r1")
    assert run["phase"] == "tool"
    assert run["phaseTool"] == "grep"
