"""Conversation-level turn queue: explicit serialisation of parallel POST messages."""

from __future__ import annotations

import asyncio

import pytest

from agentcore.runtime.events import EventSink
from agentcore.runtime.turn_queue import QueuedTurn, TurnQueue, new_queued_turn, turn_queue
from agentcore.runtime.turn_runs import TurnRunRegistry, turn_runs


async def _never() -> None:
    await asyncio.Future()


def test_enqueue_reports_visible_position_and_depth():
    q = TurnQueue()
    a = new_queued_turn(content="first", user_id="u")
    b = new_queued_turn(content="second", user_id="u")
    s1 = q.enqueue("c1", a)
    s2 = q.enqueue("c1", b)
    assert s1.position == 1 and s1.queue_depth == 1
    assert s2.position == 2 and s2.queue_depth == 2
    assert q.depth("c1") == 2
    assert q.pop_next("c1") is a
    assert q.pop_next("c1") is b
    assert q.pop_next("c1") is None


async def test_turn_done_callback_drains_module_queue(monkeypatch):
    """契约：in-flight turn 结束后按 FIFO 自动起下一回合。"""
    started: list[str] = []

    async def fake_start(conversation_id: str, item: QueuedTurn) -> None:
        started.append(item.content)

    monkeypatch.setattr(
        "agentcore.runtime.turn_queue._start_queued_turn", fake_start
    )
    turn_queue.clear("c-drain")

    blocker = asyncio.create_task(_never())
    turn_runs.register(conversation_id="c-drain", task=blocker, sink=EventSink())
    turn_queue.enqueue(
        "c-drain", new_queued_turn(content="queued-msg", user_id="u")
    )

    blocker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await blocker
    # Allow done-callback → schedule_drain → _drain → fake_start.
    for _ in range(40):
        if started:
            break
        await asyncio.sleep(0.025)
    assert started == ["queued-msg"]
    turn_queue.clear("c-drain")


async def test_enqueue_after_host_finished_arms_drain(monkeypatch):
    """竞态回归（审查①）：协调 fall-through 的附件落盘 await 期间宿主回合结束——
    done-callback 曾对空队列 no-op；enqueue_and_ensure_drain 必须补 arm，排队项不得搁浅。"""
    started_items: list[str] = []

    async def fake_start(conversation_id: str, item: QueuedTurn) -> None:
        started_items.append(item.content)

    monkeypatch.setattr("agentcore.runtime.turn_queue._start_queued_turn", fake_start)
    turn_queue.clear("c-race")

    # 复现审查竞态到达 enqueue 时的世界状态：宿主已注册→结束→done-callback 已跑
    # （schedule_drain 对空队列 no-op）→ 槽已清空。
    blocker = asyncio.create_task(_never())
    turn_runs.register(conversation_id="c-race", task=blocker, sink=EventSink())
    blocker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await blocker
    await asyncio.sleep(0.05)  # let the done-callback run its (no-op) schedule_drain
    assert turn_runs.get("c-race") is None
    assert turn_queue.depth("c-race") == 0

    # 裸 enqueue 在此态下无人再 arm drain（这就是 bug）；带守卫的入队必须自救。
    turn_queue.enqueue_and_ensure_drain(
        "c-race", new_queued_turn(content="rescued", user_id="u")
    )
    for _ in range(40):
        if started_items:
            break
        await asyncio.sleep(0.025)
    assert started_items == ["rescued"]
    turn_queue.clear("c-race")


async def test_enqueue_with_live_host_defers_to_done_callback(monkeypatch):
    """守卫对照：宿主仍在跑时 enqueue_and_ensure_drain 不抢跑——drain 仍由 done-callback 触发。"""
    started_items: list[str] = []

    async def fake_start(conversation_id: str, item: QueuedTurn) -> None:
        started_items.append(item.content)

    monkeypatch.setattr("agentcore.runtime.turn_queue._start_queued_turn", fake_start)
    turn_queue.clear("c-live")

    blocker = asyncio.create_task(_never())
    turn_runs.register(conversation_id="c-live", task=blocker, sink=EventSink())
    turn_queue.enqueue_and_ensure_drain(
        "c-live", new_queued_turn(content="waits", user_id="u")
    )
    await asyncio.sleep(0.05)
    assert started_items == []  # host live → not started early

    blocker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await blocker
    for _ in range(40):
        if started_items:
            break
        await asyncio.sleep(0.025)
    assert started_items == ["waits"]
    turn_queue.clear("c-live")


async def test_queued_waiter_receives_sink_on_drain(monkeypatch):
    """发送即有流：等待连接在 drain 时拿到 live sink（不 detach）。"""
    from agentcore.api.sse import _queued_turn_generator
    from agentcore.runtime import turn_queue as tq_mod

    handed: list[EventSink] = []
    done = asyncio.Event()

    async def fake_stream_chat(**kwargs):
        sink: EventSink = kwargs["sink"]
        handed.append(sink)
        from agentcore.runtime.events import content_delta, message_end
        from agentcore.runtime.events.types import FinishReason

        sink.emit(content_delta("from-drain"))
        sink.emit(message_end(FinishReason.END_TURN, input_tokens=1, output_tokens=1))
        sink.close()
        done.set()

    monkeypatch.setattr(
        "agentcore.conversation.service.stream_chat", fake_stream_chat
    )
    monkeypatch.setattr(
        "agentcore.runtime.turn_runs.turn_runs.register",
        lambda **kwargs: "run-id",
    )

    started: asyncio.Future[EventSink] = asyncio.get_running_loop().create_future()
    item = new_queued_turn(content="next", user_id="u", started=started)

    gen = _queued_turn_generator(
        conversation_id="c-wait",
        queue_id=item.queue_id,
        position=1,
        queue_depth=1,
        started=started,
    )
    first = await gen.__anext__()
    assert "turn_queued" in first
    assert item.queue_id in first

    await tq_mod._start_queued_turn("c-wait", item)
    assert started.done()
    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert handed and not handed[0]._detached  # noqa: SLF001

    frames: list[str] = []
    async for frame in gen:
        frames.append(frame)
    joined = "".join(frames)
    assert "from-drain" in joined
    assert "content_delta" in joined


async def test_queued_disconnect_before_drain_starts_detached(monkeypatch):
    """等待中断连 → started 取消 → drain 仍起回合但 sink.detach。"""
    detached_flags: list[bool] = []
    done = asyncio.Event()

    async def fake_stream_chat(**kwargs):
        sink: EventSink = kwargs["sink"]
        detached_flags.append(sink._detached)  # noqa: SLF001
        sink.close()
        done.set()

    monkeypatch.setattr(
        "agentcore.conversation.service.stream_chat", fake_stream_chat
    )
    monkeypatch.setattr(
        "agentcore.runtime.turn_runs.turn_runs.register",
        lambda **kwargs: "run-id",
    )

    started: asyncio.Future[EventSink] = asyncio.get_running_loop().create_future()
    started.cancel()
    item = new_queued_turn(content="orphan", user_id="u", started=started)
    from agentcore.runtime.turn_queue import _start_queued_turn

    await _start_queued_turn("c-orphan", item)
    await asyncio.wait_for(done.wait(), timeout=2.0)
    assert detached_flags == [True]


async def test_queued_disconnect_after_handoff_detaches_sink():
    """半断连回归（审查②）：drain 已 set_result、等待端在消费 sink 前断开 →
    已交付 sink 必须 detach（回合继续 detached 跑，不悬挂主观察者）。"""
    from agentcore.api.sse import _queued_turn_generator

    started: asyncio.Future[EventSink] = asyncio.get_running_loop().create_future()
    gen = _queued_turn_generator(
        conversation_id="c-half",
        queue_id="q-half",
        position=1,
        queue_depth=1,
        started=started,
    )
    first = await gen.__anext__()
    assert "turn_queued" in first

    sink = EventSink()
    started.set_result(sink)  # drain 交付 sink（视等待端为活跃 → 不 detach）…
    # …客户端恰在等待端 resume 之前断开：GeneratorExit 落在 turn_queued yield 点。
    await gen.aclose()
    assert sink._detached  # noqa: SLF001 — 断连→detached 闭环
    assert not sink._closed  # noqa: SLF001 — 回合本身不被取消/关闭（D9）


async def test_queued_disconnect_while_waiting_cancels_future():
    """对照：断连时 drain 尚未交付 → started 被取消，drain 端将以 detached 起回合。"""
    from agentcore.api.sse import _queued_turn_generator

    started: asyncio.Future[EventSink] = asyncio.get_running_loop().create_future()
    gen = _queued_turn_generator(
        conversation_id="c-pre",
        queue_id="q-pre",
        position=1,
        queue_depth=1,
        started=started,
    )
    await gen.__anext__()
    await gen.aclose()
    assert started.cancelled()


async def test_register_overlap_warning_is_the_old_grey_zone_behaviour():
    """根因钉死：直接 register 重叠会覆盖 slot（send_message 路径已改为入队）。"""
    reg = TurnRunRegistry()
    first = asyncio.create_task(_never())
    second = asyncio.create_task(_never())
    try:
        reg.register(conversation_id="c1", task=first, sink=EventSink())
        reg.register(conversation_id="c1", task=second, sink=EventSink())
        assert reg.get("c1").task is second
    finally:
        for t in (first, second):
            if not t.done():
                t.cancel()


def test_module_singleton_clear():
    turn_queue.clear("t-clear")
    turn_queue.enqueue("t-clear", new_queued_turn(content="x", user_id="u"))
    assert turn_queue.depth("t-clear") == 1
    assert turn_queue.clear("t-clear") == 1
    assert turn_queue.depth("t-clear") == 0
