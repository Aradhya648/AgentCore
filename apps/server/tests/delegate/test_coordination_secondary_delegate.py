"""Secondary delegate during coordination: merge into same session (not overwrite)."""

from __future__ import annotations

import asyncio

from agentcore.llm.provider.protocol import LLMChunk
from agentcore.runtime.coordination.session import (
    active_coordination,
    clear_active_coordination,
)
from tests.delegate.conftest import ctx, tool


class _SlowWorkers:
    """All workers sleep so the CEO can fire a second delegate mid-flight."""

    def __init__(self, texts: list[str], delay: float = 0.35) -> None:
        self._texts = texts
        self.calls = 0
        self.delay = delay

    async def stream(self, request):  # noqa: ANN001
        idx = self.calls
        self.calls += 1
        await asyncio.sleep(self.delay)
        text = self._texts[idx] if idx < len(self._texts) else "done"
        yield LLMChunk(delta_content=text)


async def test_secondary_delegate_merges_into_same_coordination_session():
    """契约：协调中二次 delegate → 同一 CoordinationSession，worker 追加，不串台。

    根因（修复前）：``set_active_coordination`` 按 execution_id 覆盖旧 session，
    旧 drive_task 仍跑但事件进被丢弃的队列；cancel / 仲裁态丢失。
    """
    clear_active_coordination()
    t = tool(_SlowWorkers(["A", "B", "C", "D"], delay=0.4))

    first = await t.execute(
        {
            "tasks": [
                {"role": "研究员", "task": "做A"},
                {"role": "写手", "task": "做B"},
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert first.success is True
    assert "团队已启动" in first.output
    session = active_coordination("e")
    assert session is not None
    session_id = id(session)
    first_drive = session.drive_task
    assert first_drive is not None and not first_drive.done()
    session.request_cancel("sentinel-keep")
    session.update_draft("保留草稿")
    budget_before = session.budget_remaining
    assert session.total_workers == 2

    second = await t.execute(
        {
            "tasks": [
                {"role": "审查", "task": "做C"},
                {"role": "校对", "task": "做D"},
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert second.success is True
    assert "队员已追加" in second.output

    after = active_coordination("e")
    assert after is not None
    assert id(after) == session_id, "must keep the same CoordinationSession object"
    assert after.total_workers == 4
    assert after.draft == "保留草稿"
    assert "sentinel-keep" in after.cancel_ids
    assert after.budget_remaining >= budget_before  # topped up, not reset/lost
    assert after.live_plan is not None
    assert len(after.live_plan.nodes) == 4
    # Live merge: original drive still owns the wave (not replaced by a second drive).
    assert after.drive_task is first_drive
    assert not first_drive.done()

    await asyncio.wait_for(first_drive, timeout=15)
    # All four workers should complete into the same session.
    assert len(after.completed_run_ids) == 4
    events = after.drain_nowait()
    from agentcore.runtime.coordination.session import CoordinationEventKind

    kinds = [e.kind for e in events]
    assert CoordinationEventKind.ALL_COMPLETED in kinds
    all_done = next(e for e in events if e.kind is CoordinationEventKind.ALL_COMPLETED)
    assert all_done.payload.get("total") == 4
    clear_active_coordination("e")


async def test_secondary_delegate_preserves_arbitration_state():
    clear_active_coordination()
    t = tool(_SlowWorkers(["A", "B", "C"], delay=0.35))
    await t.execute(
        {
            "tasks": [
                {"role": "研究员", "task": "做A"},
                {"role": "写手", "task": "做B"},
            ],
            "coordinate": True,
        },
        ctx(),
    )
    session = active_coordination("e")
    assert session is not None
    session.register_arbitration(
        "w1",
        escalation_id="esc-1",
        conversation_id="c",
        question="要不要加第三个人？",
    )
    await t.execute(
        {"tasks": [{"role": "补充", "task": "做C"}], "coordinate": True},
        ctx(),
    )
    after = active_coordination("e")
    assert after is session
    assert after.get_arbitration("w1") is not None
    assert after.total_workers == 3
    await asyncio.wait_for(session.drive_task, timeout=15)
    clear_active_coordination("e")


async def test_secondary_delegate_replaces_rewrites_downstream_depends_on():
    """Bug B: 协调补派带 replaces_run_id → 下游 depends_on 改写为新 run。"""
    clear_active_coordination()
    t = tool(_SlowWorkers(["R", "W", "R2"], delay=0.5))
    first = await t.execute(
        {
            "tasks": [
                {"id": "r1", "role": "调研", "task": "做R", "depends_on": []},
                {"id": "w", "role": "写手", "task": "做W", "depends_on": ["r1"]},
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert first.success is True
    session = active_coordination("e")
    assert session is not None and session.live_plan is not None
    r1 = next(n for n in session.live_plan.nodes if n.run_id.endswith("_r1"))
    writer = next(n for n in session.live_plan.nodes if n.run_id.endswith("_w"))
    assert r1.run_id in writer.depends_on

    second = await t.execute(
        {
            "tasks": [
                {
                    "id": "r1b",
                    "role": "调研",
                    "task": "补跑R",
                    "depends_on": [],
                    "replaces_run_id": r1.run_id,
                }
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert second.success is True
    assert "队员已追加" in second.output
    after = active_coordination("e")
    assert after is session and after.live_plan is not None
    replacement = next(
        n for n in after.live_plan.nodes if n.replaces_run_id == r1.run_id
    )
    writer_after = after.live_plan.by_id(writer.run_id)
    assert writer_after is not None
    assert replacement.run_id in writer_after.depends_on
    assert r1.run_id not in writer_after.depends_on

    await asyncio.wait_for(session.drive_task, timeout=15)
    clear_active_coordination("e")
