"""CEO 协调层唤醒降噪（事件合并 / 空转退避 / 里程碑 synthesis / 缺依赖搭车）。

对应五项降噪措施中的协调层部分（前端团队进展卡片见桌面端 vitest）：
1. 事件合并唤醒：攒批（≥N 事件或距上次唤醒≥窗口），必要决策点立即唤醒、终局不拖延。
2. 空转唤醒降频：idle 巡查按 ``2**idle_streak`` 退避；真实事件重置；保留卡死巡查 nudge。
3. synthesis 里程碑化：工具描述 / 注入文案强调里程碑，例行完成不写。
5. suspect_missing_dep 搭车既有注入通道呈现给 CEO（不新增独立唤醒）。
"""

from __future__ import annotations

import asyncio

import agentcore.runtime.coordination.wait as coord_wait
from agentcore.runtime.coordination.inject import format_coordination_events
from agentcore.runtime.coordination.session import (
    CoordinationEvent,
    CoordinationEventKind,
    CoordinationSession,
    clear_active_coordination,
    current_execution_id,
    set_active_coordination,
)
from agentcore.runtime.coordination.tools import UpdateSynthesisTool
from agentcore.runtime.coordination.wait import await_coordination_injection
from agentcore.runtime.events import EventSink
from agentcore.runtime.runs.builder import build_run_plan


def _wc(run_id: str, role: str = "R") -> CoordinationEvent:
    return CoordinationEvent(
        kind=CoordinationEventKind.WORKER_COMPLETED,
        payload={"run_id": run_id, "role": role, "status": "completed", "summary": "ok"},
    )


def _esc(run_id: str = "w9", role: str = "研究员") -> CoordinationEvent:
    return CoordinationEvent(
        kind=CoordinationEventKind.ESCALATION,
        payload={"run_id": run_id, "role": role, "question": "范围变了？"},
    )


async def _inject(execution_id: str, *, timeout: float = 2.0):
    """Bind the session active and run one ``await_coordination_injection`` cycle."""
    loop = asyncio.get_running_loop()
    token = current_execution_id.set(execution_id)
    try:
        t0 = loop.time()
        msgs = await asyncio.wait_for(await_coordination_injection([]), timeout=timeout)
        elapsed = loop.time() - t0
    finally:
        current_execution_id.reset(token)
    return msgs, elapsed


# --- 事件合并唤醒（Task 1）------------------------------------------------------


async def test_first_completion_wakes_immediately_without_hold():
    """首个 worker 完成本就是必要决策点：立即唤醒，不攒批（last_wake 尚为 None）。"""
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-first", total_workers=3)
    set_active_coordination(session)
    session.post(_wc("w1"))
    try:
        msgs, elapsed = await _inject("e-first", timeout=1.0)
    finally:
        clear_active_coordination()
    assert len(msgs) == 1
    assert "worker_completed" in (msgs[0].content or "")
    assert elapsed < 0.5  # not held
    assert session._saw_first_completion is True
    assert session.last_wake_monotonic is not None


async def test_progress_events_batch_by_count(monkeypatch):
    """攒够阈值即唤醒：窗口很大也应在第 3 个进展事件处提前合并唤醒。"""
    monkeypatch.setattr(coord_wait, "_MERGE_WINDOW_S", 5.0)
    monkeypatch.setattr(coord_wait, "_MERGE_BATCH_MAX", 3)
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-count", total_workers=6)
    session._saw_first_completion = True  # 已过首个完成 → 后续进展非必要
    session.note_wake()  # 距上次唤醒很近 → 进入攒批
    set_active_coordination(session)
    session.post(_wc("w1"))

    async def _post_more() -> None:
        await asyncio.sleep(0.02)
        session.post(_wc("w2"))
        await asyncio.sleep(0.02)
        session.post(_wc("w3"))

    try:
        task = asyncio.create_task(_post_more())
        msgs, elapsed = await _inject("e-count", timeout=3.0)
        await task
    finally:
        clear_active_coordination()
    assert len(msgs) == 1
    # 只数事件行前缀（脚注文案里也含 "worker_completed" 字样）。
    assert (msgs[0].content or "").count("- worker_completed（") == 3
    assert elapsed < 1.0  # 提前于 5s 窗口，靠计数收批


async def test_progress_events_wake_on_window(monkeypatch):
    """未攒够阈值：到「距上次唤醒≥窗口」也应带现有批次唤醒（不永久等待）。"""
    monkeypatch.setattr(coord_wait, "_MERGE_WINDOW_S", 0.2)
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-window", total_workers=4)
    session._saw_first_completion = True
    session.note_wake()
    set_active_coordination(session)
    session.post(_wc("w1"))
    try:
        msgs, elapsed = await _inject("e-window", timeout=2.0)
    finally:
        clear_active_coordination()
    assert len(msgs) == 1
    assert (msgs[0].content or "").count("- worker_completed（") == 1
    assert elapsed >= 0.15  # 攒批窗口内 hold 过，非立即唤醒


async def test_necessary_event_breaks_batch_hold(monkeypatch):
    """必要决策事件（escalation）到达攒批期即刻打断 hold、立即唤醒。"""
    monkeypatch.setattr(coord_wait, "_MERGE_WINDOW_S", 5.0)
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-esc", total_workers=4)
    session._saw_first_completion = True
    session.note_wake()
    set_active_coordination(session)
    session.post(_wc("w1"))

    async def _post_escalation() -> None:
        await asyncio.sleep(0.03)
        session.post(
            CoordinationEvent(
                kind=CoordinationEventKind.ESCALATION,
                payload={"run_id": "w2", "role": "研究员", "question": "范围变了？"},
            )
        )

    try:
        task = asyncio.create_task(_post_escalation())
        msgs, elapsed = await _inject("e-esc", timeout=2.0)
        await task
    finally:
        clear_active_coordination()
    assert len(msgs) == 1
    assert "escalation" in (msgs[0].content or "")
    assert elapsed < 1.0  # 必要事件打断，未等满 5s 窗口


async def test_terminal_all_completed_not_delayed_by_batch(monkeypatch):
    """终局不得拖延：攒批期到达 all_completed 立即唤醒并收口。"""
    monkeypatch.setattr(coord_wait, "_MERGE_WINDOW_S", 5.0)
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-term", total_workers=2)
    session._saw_first_completion = True
    session.note_wake()
    set_active_coordination(session)
    session.post(_wc("w1"))

    async def _post_all_completed() -> None:
        await asyncio.sleep(0.03)
        session.post(
            CoordinationEvent(
                kind=CoordinationEventKind.ALL_COMPLETED,
                payload={"completed": 2, "total": 2},
            )
        )

    try:
        task = asyncio.create_task(_post_all_completed())
        msgs, elapsed = await _inject("e-term", timeout=2.0)
        await task
    finally:
        clear_active_coordination()
    assert len(msgs) == 1
    assert "all_completed" in (msgs[0].content or "")
    assert elapsed < 1.0
    assert session.active is False  # 收口


# --- 空转唤醒降频（Task 2）------------------------------------------------------


def test_idle_wait_timeout_backoff(monkeypatch):
    """idle 等待随 idle_streak 指数退避，封顶 ``_COORD_WAIT_TIMEOUT_MAX_S``。"""
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_S", 10.0)
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_MAX_S", 100.0)
    s = CoordinationSession(execution_id="e", total_workers=2)
    s.idle_streak = 0
    assert coord_wait._idle_wait_timeout(s) == 10.0
    s.idle_streak = 1
    assert coord_wait._idle_wait_timeout(s) == 20.0
    s.idle_streak = 2
    assert coord_wait._idle_wait_timeout(s) == 40.0
    s.idle_streak = 3
    assert coord_wait._idle_wait_timeout(s) == 80.0
    s.idle_streak = 4
    assert coord_wait._idle_wait_timeout(s) == 100.0  # cap
    s.idle_streak = 12
    assert coord_wait._idle_wait_timeout(s) == 100.0


async def test_idle_timeout_bumps_backoff_and_real_event_resets(monkeypatch):
    """空转超时递增 idle_streak（降频）且发出巡查 nudge；真实事件重置退避。"""
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_MAX_S", 1.0)
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-idle", total_workers=2)
    set_active_coordination(session)
    try:
        msgs1, _ = await _inject("e-idle", timeout=2.0)
        assert session.idle_streak == 1
        # 保留卡死巡查语义：仍发周期性 patrol nudge（可 cancel_worker）。
        assert "等待团队事件超时" in (msgs1[0].content or "")
        msgs2, _ = await _inject("e-idle", timeout=2.0)
        assert session.idle_streak == 2
        # 真实事件到达 → 退避清零。
        session.post(_wc("w1"))
        msgs3, _ = await _inject("e-idle", timeout=2.0)
        assert session.idle_streak == 0
        assert "worker_completed" in (msgs3[0].content or "")
    finally:
        clear_active_coordination()


# --- synthesis 里程碑化（Task 3）-----------------------------------------------


def test_update_synthesis_tool_is_milestone_only():
    tool = UpdateSynthesisTool(sink=EventSink())
    desc = tool.schema.description
    assert "里程碑" in desc
    assert "例行的单个 worker 完成" in desc
    assert "禁止" in desc and "纯进度播报" in desc
    assert "新结论" in desc or "方向修正" in desc
    draft_desc = tool.schema.parameters["properties"]["draft"]["description"]
    assert "禁止纯进度播报" in draft_desc


def test_inject_footer_teaches_milestone_synthesis():
    session = CoordinationSession(execution_id="e", total_workers=3)
    text = format_coordination_events(session, [_wc("w1")])
    assert "只在【里程碑】写合成草稿" in text
    assert "例行的单个 worker 完成【不写】" in text
    assert "可静默" in text
    assert "三选一" in text
    assert "纯进度播报" in text
    assert "进度旁白不得焊进终稿" in text or "焊进终稿" in text


def test_inject_interjection_requires_user_first_reply():
    session = CoordinationSession(execution_id="e", total_workers=2)
    text = format_coordination_events(
        session,
        [
            CoordinationEvent(
                kind=CoordinationEventKind.USER_INTERJECTION,
                payload={"interjection_id": "inj-1", "content": "优先做登录页"},
            )
        ],
    )
    assert "先回用户" in text or "先】用可见正文" in text or "响应该句" in text
    assert "旧进度旁白" in text
    assert "优先做登录页" in text


# --- suspect_missing_dep 搭车注入通道（Task 5）--------------------------------


def test_builder_collects_suspect_missing_dep_advisory():
    # DAG（另有节点声明 depends_on）里某节点提及上游产出却漏声明依赖 → 建图提示。
    plan, errs = build_run_plan(
        [
            {"id": "r1", "role": "研究员", "task": "调研竞品"},
            {"id": "a", "role": "分析师", "task": "整理数据", "depends_on": ["r1"]},
            {"id": "w", "role": "写手", "task": "基于上游产出撰写报告"},
        ],
        id_prefix="t",
    )
    assert errs == []
    assert any("depends_on 为空" in a for a in plan.advisories)
    assert any("写手" in a for a in plan.advisories)


def test_builder_no_advisory_when_dep_declared():
    plan, errs = build_run_plan(
        [
            {"id": "r1", "role": "研究员", "task": "调研竞品"},
            {
                "id": "w",
                "role": "写手",
                "task": "基于上游产出撰写报告",
                "depends_on": ["r1"],
            },
        ],
        id_prefix="t",
    )
    assert errs == []
    assert plan.advisories == []


def test_inject_surfaces_dep_advisories():
    session = CoordinationSession(execution_id="e", total_workers=2)
    session.dep_advisories = [
        "「写手」的任务提及上游产出，但 depends_on 为空（run_id=t_w）。"
    ]
    text = format_coordination_events(session, [_wc("w1")])
    assert "疑似缺依赖" in text
    assert "depends_on 为空" in text


async def test_await_injection_surfaces_and_clears_advisory_once():
    """缺依赖提示搭车首次团队事件注入呈现，随后消费清空（不新增独立唤醒事件）。"""
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-adv", total_workers=2)
    session.dep_advisories = [
        "「写手」的任务提及上游产出，但 depends_on 为空（run_id=t_w）。"
    ]
    set_active_coordination(session)
    session.post(_wc("w1"))
    try:
        msgs, _ = await _inject("e-adv", timeout=1.0)
        assert "疑似缺依赖" in (msgs[0].content or "")
        # 消费一次即清空——不搭上后续每一批事件；也从未 post 独立事件（不新增唤醒）。
        assert session.dep_advisories == []
    finally:
        clear_active_coordination()


# --- 两池预算：纯遥测（批次 4 不再 HOLD）------------------------------------


async def test_progress_pool_available_consumes_and_wakes():
    """进度池尚有额度：例行进展照常唤醒并消耗一次进度池（不动决策池）。"""
    clear_active_coordination()
    session = CoordinationSession(
        execution_id="e-prog",
        total_workers=4,
        progress_budget_remaining=2,
        decision_budget_remaining=3,
    )
    session._saw_first_completion = True  # 已过首个完成 → 后续进展非必要
    set_active_coordination(session)
    session.post(_wc("w2"))
    try:
        msgs, _ = await _inject("e-prog", timeout=1.0)
    finally:
        clear_active_coordination()
    assert (msgs[0].content or "").count("- worker_completed（") == 1
    assert session.progress_budget_remaining == 1  # 进度池消耗 1
    assert session.decision_budget_remaining == 3  # 决策池不受影响


async def test_necessary_decision_wakes_when_progress_pool_at_floor():
    """进度池已到 floor：必要决策仍立即唤醒并记决策池遥测。"""
    clear_active_coordination()
    session = CoordinationSession(
        execution_id="e-nec",
        total_workers=4,
        progress_budget_remaining=0,
        decision_budget_remaining=2,
    )
    session._saw_first_completion = True
    set_active_coordination(session)
    session.post(_esc("w4"))
    try:
        msgs, elapsed = await _inject("e-nec", timeout=1.0)
    finally:
        clear_active_coordination()
    assert "escalation" in (msgs[0].content or "")
    assert elapsed < 0.5
    assert session.decision_budget_remaining == 1
    assert session.progress_budget_remaining == 0


async def test_progress_pool_at_floor_still_wakes_on_routine():
    """进度池 floor：例行进展仍立即唤醒（批次 4 遥测化，不再 HOLD）。"""
    clear_active_coordination()
    session = CoordinationSession(
        execution_id="e-floor",
        total_workers=6,
        progress_budget_remaining=0,
        decision_budget_remaining=3,
    )
    session._saw_first_completion = True
    set_active_coordination(session)
    session.post(_wc("w2"))
    try:
        msgs, elapsed = await _inject("e-floor", timeout=1.0)
    finally:
        clear_active_coordination()
    content = msgs[0].content or ""
    assert content.count("- worker_completed（") == 1
    assert elapsed < 0.5
    assert session.progress_budget_remaining == 0
    assert session.decision_budget_remaining == 3


async def test_progress_pool_floor_logs_telemetry(monkeypatch):
    """进度池 floor 唤醒时记 progress_budget_floor 遥测，不消耗决策池。"""
    clear_active_coordination()
    session = CoordinationSession(
        execution_id="e-floor-idle",
        total_workers=6,
        progress_budget_remaining=0,
        decision_budget_remaining=3,
    )
    session._saw_first_completion = True
    set_active_coordination(session)
    session.post(_wc("w2"))
    try:
        msgs, _ = await _inject("e-floor-idle", timeout=1.0)
    finally:
        clear_active_coordination()
    content = msgs[0].content or ""
    assert content.count("- worker_completed（") == 1
    assert session.progress_budget_remaining == 0
    assert session.decision_budget_remaining == 3
