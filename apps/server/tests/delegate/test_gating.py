"""Local-mode worker gating tests."""

from agentcore.runtime.events import EventSink, EventType
from tests.delegate.conftest import (
    Provider,
    capture_gate,
    ctx,
    gate,
    local_ctx,
    tool,
    tool_with_gate,
)


async def test_workers_gated_in_local_mode(monkeypatch):
    # Skip kickoff so the executor path runs (gate forwarding is what we assert).
    monkeypatch.setattr(
        "agentcore.runtime.delegate.preview.should_kickoff",
        lambda *a, **k: False,
    )
    captured = capture_gate(monkeypatch)
    g = gate()
    t = tool_with_gate(local_ctx(), g)
    await t.execute({"tasks": [{"role": "A", "task": "a"}]}, local_ctx())
    assert captured["gate"] is g


async def test_workers_ungated_in_cloud_mode(monkeypatch):
    captured = capture_gate(monkeypatch)
    t = tool_with_gate(ctx(), gate())
    await t.execute({"tasks": [{"role": "A", "task": "a"}]}, ctx())
    assert captured["gate"] is None


async def test_second_call_namespaces_run_ids():
    sink = EventSink()
    t = tool(Provider(["X", "Y"]), sink=sink)
    await t.execute({"tasks": [{"role": "A", "task": "a"}]}, ctx())
    await t.execute({"tasks": [{"role": "B", "task": "b"}]}, ctx())
    sink.close()
    starts = [e async for e in sink if e.type == EventType.RUN_STARTED]
    run_ids = [e.payload["run_id"] for e in starts]
    assert len(run_ids) == 2
    assert run_ids[0] != run_ids[1]
