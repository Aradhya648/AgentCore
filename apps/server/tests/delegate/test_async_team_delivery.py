"""批次 1：异步团队产出投递 — 四支柱回归。"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, patch

import pytest

from agentcore.runtime.coordination.session import (
    CoordinationSession,
    active_coordination,
    active_coordination_for_conversation,
    adopt_active_execution,
    bind_host_journal,
    clear_active_coordination,
    emit_execution_detached,
    finish_detached_coordination,
    release_turn_coordination,
    set_active_coordination,
)
from agentcore.runtime.events import EventSink, EventType, execution_completed
from agentcore.runtime.events.types import SSEEvent
from agentcore.runtime.journal.fold import _splice_synthetic_deltas


@pytest.fixture(autouse=True)
def _clean_coordination():
    clear_active_coordination()
    yield
    clear_active_coordination()


class _RecordingWriter:
    """Minimal journal writer stand-in for closed-sink DURABLE persistence."""

    def __init__(self, turn_id: str = "host-turn") -> None:
        self.turn_id = turn_id
        self.sealed = False
        self.entries: list[dict] = []

    def schedule_append(self, entry: dict):
        self.entries.append(entry)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[int | None] = loop.create_future()
        fut.set_result(len(self.entries))
        return fut

    async def flush(self) -> None:
        return None


@pytest.mark.asyncio
async def test_pillar_a_closed_sink_persists_run_completed_via_host_writer():
    """支柱 A：sink 关闭后 DURABLE 仍经 execution host writer 落盘。"""
    writer = _RecordingWriter()
    session = CoordinationSession(
        execution_id="exec-a",
        total_workers=1,
        conversation_id="conv-a",
    )
    bind_host_journal(session, writer=writer, turn_id="host-turn")
    set_active_coordination(session)

    sink = EventSink(conversation_id="conv-a", message_id="host-turn")
    sink.close()

    sink.emit(
        SSEEvent(
            type=EventType.RUN_COMPLETED,
            payload={
                "run_id": "r1",
                "agent_id": "w1",
                "output_summary": "队员正文",
                "duration_ms": 10,
                "role": "member",
                "model": "test",
                "usage": {"input": 1, "output": 1, "total": 2},
                "cost": {
                    "input": 0,
                    "cached": 0,
                    "output": 0,
                    "total": 0,
                    "currency": "USD",
                },
                "execution_id": "exec-a",
            },
        )
    )

    kinds = [e.get("kind") for e in writer.entries]
    assert EventType.RUN_COMPLETED.value in kinds


@pytest.mark.asyncio
async def test_pillar_a_closed_sink_persists_without_payload_execution_id():
    """支柱 A：payload 无 execution_id + ContextVar 清空后，经 conversation 注册表落盘。"""
    from agentcore.runtime.coordination.session import current_execution_id
    from agentcore.runtime.journal.writer import current_journal_writer

    writer = _RecordingWriter()
    session = CoordinationSession(
        execution_id="exec-a-fallback",
        total_workers=1,
        conversation_id="conv-a-fallback",
    )
    bind_host_journal(session, writer=writer, turn_id="host-turn")
    set_active_coordination(session)

    # Simulate turn teardown: journal writer + execution ContextVars reset, but
    # conversation→execution registry still holds the live session.
    jw_token = current_journal_writer.set(None)
    eid_token = current_execution_id.set(None)
    try:
        sink = EventSink(conversation_id="conv-a-fallback", message_id="host-turn")
        sink.close()
        sink.emit(
            SSEEvent(
                type=EventType.RUN_COMPLETED,
                payload={
                    "run_id": "r1",
                    "agent_id": "w1",
                    "output_summary": "队员正文",
                    "duration_ms": 10,
                    "role": "member",
                    "model": "test",
                    "usage": {"input": 1, "output": 1, "total": 2},
                    "cost": {
                        "input": 0,
                        "cached": 0,
                        "output": 0,
                        "total": 0,
                        "currency": "USD",
                    },
                    # intentionally no execution_id — production hole before fix
                },
            )
        )
    finally:
        current_journal_writer.reset(jw_token)
        current_execution_id.reset(eid_token)

    kinds = [e.get("kind") for e in writer.entries]
    assert EventType.RUN_COMPLETED.value in kinds


def test_run_completed_factory_carries_execution_id_when_set():
    """生产工厂：非空 execution_id 写入 payload；空串保持旧 fixture 字节兼容。"""
    from agentcore.runtime.events import run_completed

    with_eid = run_completed(
        "r1",
        "w1",
        output_summary="done",
        duration_ms=1,
        execution_id="exec-factory",
    )
    assert with_eid.payload["execution_id"] == "exec-factory"

    without = run_completed("r1", "w1", output_summary="done", duration_ms=1)
    assert "execution_id" not in without.payload


@pytest.mark.asyncio
async def test_pillar_a_fold_rebuilds_member_output_from_journal_facts():
    """支柱 A：message_final + run_completed → fold 拼出队员正文。"""
    events = [
        {
            "type": "run_started",
            "payload": {"run_id": "r1", "agent_id": "w1", "role": "研究员"},
            "timestamp": "2026-01-01T00:00:00.000Z",
        },
        {
            "type": "run_completed",
            "payload": {
                "run_id": "r1",
                "agent_id": "w1",
                "output_summary": "完整调研结论",
                "duration_ms": 100,
                "role": "member",
                "model": "test",
                "usage": {"input": 1, "output": 1, "total": 2},
                "cost": {
                    "input": 0,
                    "cached": 0,
                    "output": 0,
                    "total": 0,
                    "currency": "USD",
                },
            },
            "timestamp": "2026-01-01T00:00:01.000Z",
        },
    ]
    finals = {"r1": {"content": "完整调研结论", "reasoning": "思考过程"}}
    agent_runs = {"r1": "w1"}
    spliced = _splice_synthetic_deltas(events, finals, agent_runs)
    types = [e["type"] for e in spliced]
    assert EventType.RUN_REASONING_DELTA.value in types
    assert EventType.RUN_OUTPUT_DELTA.value in types
    assert EventType.RUN_COMPLETED.value in types
    out = next(e for e in spliced if e["type"] == EventType.RUN_OUTPUT_DELTA.value)
    assert out["payload"]["delta"] == "完整调研结论"


@pytest.mark.asyncio
async def test_pillar_b_registry_is_routing_source_for_adopt():
    """支柱 B：conversation→execution 注册表收养后 ContextVar 指向活跃执行。"""
    session = CoordinationSession(
        execution_id="exec-b",
        total_workers=2,
        conversation_id="conv-b",
    )
    set_active_coordination(session)
    assert active_coordination_for_conversation("conv-b") is session

    adopted = adopt_active_execution("conv-b")
    assert adopted is session
    assert session.turn_attached is True
    assert active_coordination() is session


@pytest.mark.asyncio
async def test_pillar_b_release_emits_detached_and_keeps_registry():
    """支柱 B/D：teardown 发 execution_detached，注册表保留 live drive。"""
    writer = _RecordingWriter()

    async def _slow():
        await asyncio.sleep(0.2)

    session = CoordinationSession(
        execution_id="exec-detach",
        total_workers=2,
        conversation_id="conv-detach",
    )
    bind_host_journal(session, writer=writer)
    session.drive_task = asyncio.create_task(_slow())
    set_active_coordination(session)

    release_turn_coordination("exec-detach")
    assert session.turn_attached is False
    assert active_coordination("exec-detach") is session
    kinds = [e.get("kind") for e in writer.entries]
    assert EventType.EXECUTION_DETACHED.value in kinds

    session.drive_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await session.drive_task


@pytest.mark.asyncio
async def test_pillar_c_finish_detached_schedules_harvest():
    """支柱 C：无附着回合时 finish_detached 调度收割（非静默 clear）。"""
    session = CoordinationSession(
        execution_id="exec-c",
        total_workers=1,
        conversation_id="conv-c",
    )
    set_active_coordination(session)
    session.turn_attached = False

    with patch(
        "agentcore.runtime.coordination.harvest.harvest_detached_execution",
        new_callable=AsyncMock,
    ) as harvest:
        finish_detached_coordination(session)
        assert session.harvest_scheduled is True
        await asyncio.sleep(0.05)
        harvest.assert_awaited_once()


@pytest.mark.asyncio
async def test_pillar_c_harvest_skips_when_reattached():
    from agentcore.runtime.coordination.harvest import harvest_detached_execution

    session = CoordinationSession(
        execution_id="exec-c2",
        total_workers=1,
        conversation_id="conv-c2",
    )
    session.turn_attached = True
    set_active_coordination(session)
    await harvest_detached_execution(session)
    assert active_coordination("exec-c2") is session


@pytest.mark.asyncio
async def test_pillar_c_harvest_deferred_keeps_registry_and_retries():
    """槽位占用时不得当成成功收口清注册表；须保留并可再收获。"""
    import agentcore.conversation.execution_harvest as eh
    from agentcore.conversation.execution_harvest import HarvestDeferredError
    from agentcore.runtime.coordination import harvest as harvest_mod

    session = CoordinationSession(
        execution_id="exec-deferred",
        total_workers=1,
        conversation_id="conv-deferred",
    )
    session.turn_attached = False
    set_active_coordination(session)

    calls = {"n": 0}

    async def _closing(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise HarvestDeferredError("conv-deferred", "exec-deferred")
        # Second attempt succeeds (no-op closing).

    with (
        patch.object(harvest_mod, "_HARVEST_RETRY_DELAY_S", 0.01),
        patch.object(eh, "run_harvest_closing_turn", new=_closing),
    ):
        await harvest_mod.harvest_detached_execution(session)

    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_pillar_c_harvest_deferred_does_not_close_on_slot_busy():
    """Deferred 耗尽仍保留注册，禁止「只清注册表、用户无下文」。"""
    import agentcore.conversation.execution_harvest as eh
    from agentcore.conversation.execution_harvest import HarvestDeferredError
    from agentcore.runtime.coordination import harvest as harvest_mod

    session = CoordinationSession(
        execution_id="exec-busy",
        total_workers=1,
        conversation_id="conv-busy",
    )
    session.turn_attached = False
    set_active_coordination(session)

    async def _always_deferred(**_kwargs):
        raise HarvestDeferredError("conv-busy", "exec-busy")

    with (
        patch.object(harvest_mod, "_HARVEST_MAX_ATTEMPTS", 3),
        patch.object(harvest_mod, "_HARVEST_RETRY_DELAY_S", 0.01),
        patch.object(eh, "run_harvest_closing_turn", new=_always_deferred),
    ):
        await harvest_mod.harvest_detached_execution(session)

    assert active_coordination("exec-busy") is session


def test_harvest_user_text_distinguishes_outcomes():
    from agentcore.conversation.execution_harvest import (
        format_harvest_user_text,
        harvest_closing_kind,
    )
    from agentcore.runtime.coordination.session import (
        CoordinationEvent,
        CoordinationEventKind,
    )

    ok = CoordinationSession(execution_id="h-ok", total_workers=2)
    ok.completed_run_ids = {"a", "b"}
    assert harvest_closing_kind(ok) == "success"
    assert "已全部完成" in format_harvest_user_text(ok)

    fail = CoordinationSession(execution_id="h-fail", total_workers=2)
    fail.completed_run_ids = {"a", "b"}
    fail.failed_run_ids = {"b"}
    assert harvest_closing_kind(fail) == "failure"
    text_fail = format_harvest_user_text(fail)
    assert "失败" in text_fail
    assert "任务已全部完成" not in text_fail

    cancelled = CoordinationSession(execution_id="h-cancel", total_workers=1)
    cancelled.soft_stop = True
    assert harvest_closing_kind(cancelled) == "cancelled"
    text_c = format_harvest_user_text(cancelled)
    assert "取消" in text_c
    assert "任务已全部完成" not in text_c
    assert text_c.startswith("【系统收口】后台团队任务已取消")

    drive_c = CoordinationSession(execution_id="h-drive-c", total_workers=1)
    drive_c._pending.append(
        CoordinationEvent(kind=CoordinationEventKind.DRIVE_CANCELLED, payload={})
    )
    assert harvest_closing_kind(drive_c) == "cancelled"
    assert format_harvest_user_text(drive_c).startswith(
        "【系统收口】后台团队任务已取消"
    )


@pytest.mark.asyncio
async def test_pillar_d_await_live_detached_drive_delays_until_done():
    """支柱 D1：pipeline 返回后有 live detached drive 时，sink.close 须等 drive 结束。"""
    from agentcore.runtime.coordination.session import await_live_detached_drive

    release = asyncio.Event()

    async def _slow():
        await release.wait()

    session = CoordinationSession(
        execution_id="exec-d1-delay",
        total_workers=2,
        conversation_id="conv-d1-delay",
    )
    session.drive_task = asyncio.create_task(_slow())
    session.turn_attached = False  # already detached (post release_turn)
    set_active_coordination(session)

    sink = EventSink(conversation_id="conv-d1-delay", message_id="host-turn")
    closed = asyncio.Event()

    async def _owner_close_path():
        # Mirrors sidecar/cloud: await drive, then close.
        awaited = await await_live_detached_drive("conv-d1-delay")
        assert awaited is True
        sink.close()
        closed.set()

    owner = asyncio.create_task(_owner_close_path())
    await asyncio.sleep(0.05)
    assert not closed.is_set()
    assert not sink._closed

    # Live events still land on the open sink while we wait.
    sink.emit(
        SSEEvent(
            type=EventType.RUN_COMPLETED,
            payload={
                "run_id": "r1",
                "agent_id": "w1",
                "output_summary": "done",
                "duration_ms": 1,
            },
        )
    )

    release.set()
    await asyncio.wait_for(owner, timeout=2)
    assert sink._closed
    assert closed.is_set()


@pytest.mark.asyncio
async def test_pillar_d_await_skips_when_no_live_detached_drive():
    """无 live detached drive（仍附着 / 已停 / 无 session）→ 立即返回，不阻塞 close。"""
    from agentcore.runtime.coordination.session import await_live_detached_drive

    assert await await_live_detached_drive("missing") is False

    async def _slow():
        await asyncio.sleep(30)

    session = CoordinationSession(
        execution_id="exec-d1-attached",
        total_workers=1,
        conversation_id="conv-d1-attached",
    )
    session.drive_task = asyncio.create_task(_slow())
    session.turn_attached = True  # still arming turn
    set_active_coordination(session)
    assert await await_live_detached_drive("conv-d1-attached") is False

    session.drive_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await session.drive_task


@pytest.mark.asyncio
async def test_pillar_d_execution_events_factories():
    """支柱 D：协议事件工厂形状。"""
    session = CoordinationSession(
        execution_id="exec-d",
        total_workers=3,
        conversation_id="conv-d",
    )
    writer = _RecordingWriter()
    bind_host_journal(session, writer=writer)
    set_active_coordination(session)
    session.turn_attached = False
    emit_execution_detached(session, reason="early_close")
    assert any(e.get("kind") == "execution_detached" for e in writer.entries)

    done = execution_completed(
        execution_id="exec-d",
        conversation_id="conv-d",
        completed=3,
        total=3,
    )
    assert done.type is EventType.EXECUTION_COMPLETED
    assert done.payload["completed"] == 3
