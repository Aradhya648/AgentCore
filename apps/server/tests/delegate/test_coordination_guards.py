"""Guards: idle-patrol activity check, isomorphic re-delegation, user_stop cascade."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agentcore.runtime.coordination import wait as coord_wait
from agentcore.runtime.coordination.isomorphic import (
    is_isomorphic_redelegation,
    tasks_similar,
)
from agentcore.runtime.coordination.session import (
    CoordinationSession,
    active_coordination,
    cancel_coordination_on_user_stop,
    clear_active_coordination,
    release_turn_coordination,
    set_active_coordination,
)
from agentcore.runtime.coordination.wait import await_coordination_injection
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunSpec
from agentcore.runtime.turn_interrupt import TurnInterruptReason, compose_interrupt_body
from agentcore.runtime.turn_runs import TurnRun, turn_runs


def _plan(*nodes: RunSpec) -> RunPlan:
    plan = RunPlan()
    for n in nodes:
        plan.add(n)
    return plan


# --- A: idle patrol activity -------------------------------------------------


def test_has_inflight_work_and_progress_summary():
    s = CoordinationSession(execution_id="e", total_workers=2)
    # Avoid arm_worker_timeout (needs a running loop); stamp registry directly.
    s._running_workers["w1"] = "研究员"
    s._running_workers["w2"] = "写手"
    s._worker_started_at["w1"] = s._worker_started_at["w2"] = __import__("time").monotonic()
    assert s.has_inflight_work() is False
    s.mark_worker_busy("w1", "llm")
    assert s.has_inflight_work() is True
    summary = s.worker_progress_summary()
    assert "研究员" in summary
    assert "LLM 调用中" in summary
    assert "写手" in summary
    s.clear_worker_busy("w1")
    assert s.has_inflight_work() is False


async def test_idle_timeout_defers_when_workers_busy(monkeypatch):
    """Workers mid-LLM → idle window expires but no patrol nudge; real event still wakes."""
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_MAX_S", 1.0)
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-busy", total_workers=1)
    session._running_workers["w1"] = "研究员"
    session._worker_started_at["w1"] = __import__("time").monotonic()
    session.mark_worker_busy("w1", "llm")
    # Fake a live drive so wait does not short-circuit as team_done.
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        async def _post_later() -> None:
            # Stay busy across ≥1 idle window, then post while still busy so the
            # wait returns the real event (not a racey idle_timeout after clear).
            await asyncio.sleep(0.12)
            from agentcore.runtime.coordination.session import (
                CoordinationEvent,
                CoordinationEventKind,
            )

            session.post(
                CoordinationEvent(
                    kind=CoordinationEventKind.WORKER_COMPLETED,
                    payload={"run_id": "w1", "role": "研究员", "status": "completed"},
                )
            )

        helper = asyncio.create_task(_post_later())
        msgs = await asyncio.wait_for(await_coordination_injection([]), timeout=3.0)
        await helper
        text = msgs[0].content or ""
        assert "等待团队事件超时" not in text
        assert "worker_completed" in text or "研究员" in text
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination()


async def test_idle_timeout_patrols_when_truly_stalled(monkeypatch):
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_MAX_S", 1.0)
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-stall", total_workers=1)
    session._running_workers["w1"] = "研究员"
    session._worker_started_at["w1"] = __import__("time").monotonic()
    # Registered but not busy → true stall → patrol with progress summary.
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        msgs = await asyncio.wait_for(await_coordination_injection([]), timeout=2.0)
        text = msgs[0].content or ""
        assert "等待团队事件超时" in text
        assert "研究员" in text
        assert session.idle_streak == 1
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination()


# --- B: isomorphic re-delegation --------------------------------------------


def test_tasks_similar_and_isomorphic_plan():
    assert tasks_similar("调研竞品格局", "调研竞品格局并整理要点")
    assert not tasks_similar("调研竞品", "撰写最终报告")
    live = _plan(
        RunSpec(run_id="a", role="法律研究员", task="梳理相关法条与司法解释"),
        RunSpec(run_id="b", role="实务案例分析师", task="归纳典型判例要点"),
        RunSpec(run_id="c", role="实务写作专家", task="撰写实务研究成稿"),
    )
    twin = _plan(
        RunSpec(run_id="a2", role="法律研究员", task="梳理相关法条与司法解释要点"),
        RunSpec(run_id="b2", role="实务案例分析师", task="归纳典型判例要点并对照"),
        RunSpec(run_id="c2", role="实务写作专家", task="撰写实务研究成稿"),
    )
    assert is_isomorphic_redelegation(twin, live, completed_run_ids=set()) is True
    different = _plan(
        RunSpec(run_id="d", role="审计员", task="独立审查成稿质量"),
    )
    assert is_isomorphic_redelegation(different, live, completed_run_ids=set()) is False


async def test_secondary_isomorphic_delegate_rejected():
    from agentcore.runtime.events import EventSink, EventType
    from tests.delegate.conftest import ctx, tool
    from tests.delegate.test_coordination_secondary_delegate import _SlowWorkers

    clear_active_coordination()
    sink = EventSink()
    t = tool(_SlowWorkers(["A", "B", "C", "D"], delay=0.5), sink=sink)
    first = await t.execute(
        {
            "tasks": [
                {"role": "研究员", "task": "做A调研"},
                {"role": "写手", "task": "做B撰写"},
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert first.success is True
    session = active_coordination("e")
    assert session is not None
    drive = session.drive_task
    assert drive is not None and not drive.done()
    assert len([e for e in sink._history if e.type is EventType.RUN_PLAN]) == 1

    second = await t.execute(
        {
            "tasks": [
                {"role": "研究员", "task": "做A调研补充"},
                {"role": "写手", "task": "做B撰写完善"},
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert second.success is False
    assert "同构" in (second.error or "")
    assert second.contract_failure is True
    assert session.total_workers == 2
    # 同构拒在 emit 前：不得留下第二张 durable run_plan。
    assert len([e for e in sink._history if e.type is EventType.RUN_PLAN]) == 1

    # 同构连拒不得推进熔断。
    from agentcore.runtime.loop_controller import LoopController, ToolAttempt

    breaker = LoopController()
    for i in range(5):
        breaker.record(
            [
                ToolAttempt(
                    f"iso{i}",
                    "delegate",
                    success=False,
                    contract_failure=second.contract_failure,
                )
            ]
        )
        assert not breaker.tool_circuit_breaker()

    # force=true allows the merge.
    forced = await t.execute(
        {
            "tasks": [
                {"role": "审查", "task": "做C审查"},
            ],
            "coordinate": True,
            "force": True,
        },
        ctx(),
    )
    # Non-isomorphic + force still merges; isomorphic+force also merges.
    assert forced.success is True
    assert session.total_workers >= 3

    drive.cancel()
    with pytest.raises(asyncio.CancelledError):
        await drive
    clear_active_coordination("e")


# --- B1b: thrash rebrand cold-delegate ---------------------------------------


async def test_thrash_rebrand_cold_delegate_rejected_continue_and_force():
    """Cold similar task after thrash → reject; continue_from / force pass."""
    from agentcore.runtime.coordination.thrash import (
        ThrashRecord,
        clear_thrash_registry,
        note_thrashing_worker,
    )
    from agentcore.runtime.events import EventSink
    from tests.delegate.conftest import ctx, tool
    from tests.delegate.test_coordination_secondary_delegate import _SlowWorkers

    clear_thrash_registry()
    clear_active_coordination()
    sink = EventSink()
    t = tool(_SlowWorkers(["ok"], delay=0.05), sink=sink)
    t._conversation_id = "thrash-conv"

    note_thrashing_worker(
        "thrash-conv",
        ThrashRecord(
            run_id="prior-thrash",
            task="修复 TopBar 缺少 named export",
            artifacts=("src/TopBar.tsx",),
            role="工程师",
        ),
    )

    cold = await t.execute(
        {
            "tasks": [
                {
                    "role": "修码员",
                    "task": "修复 TopBar named export 缺失",
                    "deliverable": {
                        "form": "files",
                        "requires_files": True,
                        "artifacts": ["src/TopBar.tsx"],
                    },
                }
            ],
            "coordinate": False,
        },
        ctx(),
    )
    assert cold.success is False
    assert "触顶换马甲" in (cold.error or "")
    assert "continue_from_run_id=`prior-thrash`" in (cold.error or "")
    assert cold.contract_failure is True

    cont = await t.execute(
        {
            "tasks": [
                {
                    "role": "修码员",
                    "task": "修复 TopBar named export 缺失",
                    "continue_from_run_id": "prior-thrash",
                    "deliverable": {
                        "form": "files",
                        "requires_files": True,
                        "artifacts": ["src/TopBar.tsx"],
                    },
                }
            ],
            "coordinate": False,
        },
        ctx(),
    )
    # continue_from may still fail session lookup; admission must not thrash-reject.
    assert "触顶换马甲" not in (cont.error or "")

    forced = await t.execute(
        {
            "tasks": [
                {
                    "role": "新人",
                    "task": "修复 TopBar named export 缺失",
                    "deliverable": {
                        "form": "files",
                        "requires_files": True,
                        "artifacts": ["src/TopBar.tsx"],
                    },
                }
            ],
            "coordinate": False,
            "force": True,
        },
        ctx(),
    )
    assert forced.success is True
    clear_thrash_registry("thrash-conv")
    clear_active_coordination()


# --- B2: merge run_id collision receipts ------------------------------------


def _fake_merge_tool(*, force: bool = False) -> MagicMock:
    tool = MagicMock()
    tool._sink = MagicMock()
    # MagicMock would otherwise make getattr(_delegate_force) truthy and bypass guards.
    tool._delegate_force = force
    return tool


# --- B3: append overlap guard (role / deliverable) --------------------------


def test_roles_and_file_targets_detect_geo_class_overlap():
    from agentcore.runtime.coordination.append_guard import (
        find_append_overlaps,
        node_file_targets,
        roles_overlap,
    )
    from agentcore.runtime.runs.types import Deliverable

    assert roles_overlap("内容文案", "内容策略")
    assert roles_overlap("页面 QA", "页面 QA")
    assert not roles_overlap("前端工程师", "测试工程师")
    assert not roles_overlap("SEO 优化师", "内容文案")

    skeleton = RunSpec(
        run_id="skeleton",
        role="骨架工程师",
        task="写 site/index.html 与 site/styles.css",
        deliverable=Deliverable(
            form="files",
            name="骨架",
            artifacts=["site/index.html", "site/styles.css", "site/main.js"],
        ),
    )
    frontend = RunSpec(
        run_id="fe",
        role="前端工程师",
        task="基于文案实现整站，写入 site/index.html",
        deliverable=Deliverable(
            form="files",
            name="整站前端",
            artifacts=["site/index.html"],
        ),
    )
    assert "site/index.html" in node_file_targets(skeleton)
    assert "site/index.html" in node_file_targets(frontend)

    live = _plan(
        RunSpec(
            run_id="copy",
            role="内容文案",
            task="撰写文案落盘 site/copy.md",
            deliverable=Deliverable(artifacts=["site/copy.md"]),
        ),
        skeleton,
        RunSpec(run_id="qa", role="页面 QA", task="质检并写 site/QA.md"),
    )
    overlapping = _plan(frontend)
    hits = find_append_overlaps(overlapping, live, completed_run_ids=set())
    assert hits
    assert hits[0].reason in ("deliverable", "role+deliverable")

    non_overlap = _plan(
        RunSpec(run_id="seo", role="SEO 优化师", task="整理站外外链策略备忘"),
    )
    assert find_append_overlaps(non_overlap, live, completed_run_ids=set()) == []


async def test_merge_rejects_overlapping_append_with_explanation():
    """DAG 未完成时追加职责/文件重叠队员 → 拒绝且回执含解释。"""
    from agentcore.runtime.coordination.host import _merge_into_active_coordination
    from agentcore.runtime.runs.types import Deliverable

    clear_active_coordination()
    live = _plan(
        RunSpec(
            run_id="copy",
            role="内容文案",
            task="写 site/copy.md",
            deliverable=Deliverable(artifacts=["site/copy.md"]),
            depends_on=[],
        ),
        RunSpec(
            run_id="skeleton",
            role="骨架工程师",
            task="写 site/index.html",
            deliverable=Deliverable(artifacts=["site/index.html"]),
            depends_on=["copy"],
        ),
    )
    session = CoordinationSession(execution_id="e-overlap", total_workers=2)
    session.live_plan = live
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        overlapping = _plan(
            RunSpec(
                run_id="dup_copy",
                role="内容策略",
                task="为官网撰写各版块文案并落盘 site/copy.md",
                deliverable=Deliverable(artifacts=["site/copy.md"]),
            )
        )
        result = _merge_into_active_coordination(
            _fake_merge_tool(),
            overlapping,
            session,
            execution_id="e-overlap",
            seed_completed=None,
            finalize=False,
            seed_notes=None,
            complexity_hint="",
            call_idx=2,
            completion_criteria=None,
            coordination="none",
        )
        assert result.success is False
        err = result.error or ""
        assert "重叠" in err
        assert "波次" in err or "等待" in err
        assert result.contract_failure is True
        assert session.total_workers == 2
        assert len(live.nodes) == 2
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination("e-overlap")


async def test_merge_allows_non_overlapping_append():
    """流水线外新增职责（无角色/文件重叠）仍放行。"""
    from agentcore.runtime.coordination.host import _merge_into_active_coordination
    from agentcore.runtime.runs.types import Deliverable

    clear_active_coordination()
    live = _plan(
        RunSpec(
            run_id="copy",
            role="内容文案",
            task="写 site/copy.md",
            deliverable=Deliverable(artifacts=["site/copy.md"]),
        ),
        RunSpec(
            run_id="skeleton",
            role="骨架工程师",
            task="写 site/index.html",
            deliverable=Deliverable(artifacts=["site/index.html"]),
            depends_on=["copy"],
        ),
    )
    session = CoordinationSession(execution_id="e-ok-append", total_workers=2)
    session.live_plan = live
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        extra = _plan(
            RunSpec(
                run_id="legal",
                role="合规顾问",
                task="审核品牌用语是否触碰广告法红线，产出备忘（不写站点文件）",
            )
        )
        result = _merge_into_active_coordination(
            _fake_merge_tool(),
            extra,
            session,
            execution_id="e-ok-append",
            seed_completed=None,
            finalize=False,
            seed_notes=None,
            complexity_hint="",
            call_idx=2,
            completion_criteria=None,
            coordination="none",
        )
        assert result.success is True
        assert session.total_workers == 3
        assert any(n.run_id == "legal" for n in live.nodes)
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination("e-ok-append")


def test_healthy_idle_inject_has_progress_and_no_action_guidance():
    """健康流水线 idle 注入含进度视图，并明确导向无需追加动作。"""
    from agentcore.runtime.coordination.inject import idle_yield_messages
    from agentcore.runtime.coordination.pipeline_view import (
        format_idle_yield_brief,
        is_pipeline_healthy,
    )
    from agentcore.runtime.runs.types import Deliverable

    live = _plan(
        RunSpec(
            run_id="copy",
            role="内容文案",
            task="写 site/copy.md",
            deliverable=Deliverable(artifacts=["site/copy.md"]),
        ),
        RunSpec(
            run_id="skeleton",
            role="骨架工程师",
            task="写 site/index.html",
            deliverable=Deliverable(artifacts=["site/index.html"]),
            depends_on=["copy"],
        ),
        RunSpec(
            run_id="qa",
            role="页面 QA",
            task="质检",
            depends_on=["skeleton"],
        ),
    )
    session = CoordinationSession(execution_id="e-idle", total_workers=3)
    session.live_plan = live
    session._running_workers["copy"] = "内容文案"
    session._worker_started_at["copy"] = __import__("time").monotonic()
    session.mark_worker_busy("copy", "llm")

    assert is_pipeline_healthy(session) is True
    brief = format_idle_yield_brief(session)
    assert "流水线进度" in brief
    assert "Wave" in brief
    assert "在跑" in brief or "内容文案" in brief
    assert "依赖阻塞" in brief
    assert "无需追加" in brief
    assert "正常推进" in brief
    assert "不要 delegate" in brief or "勿" in brief
    assert "完成后会再汇报" in brief
    assert "保持静默即可" not in brief
    assert "保持等待" in brief or "保持静默" in brief  # forbid phrasing appears as prohibition

    msgs = idle_yield_messages(session)
    assert len(msgs) == 1
    assert "流水线进度" in (msgs[0].content or "")
    assert "无需追加" in (msgs[0].content or "")
    assert "完成后会再汇报" in (msgs[0].content or "")
    assert "保持静默即可" not in (msgs[0].content or "")


def test_idle_yield_brief_pending_approval_forbids_wait(monkeypatch):
    """有热路 pending 时 idle_yield 文案禁止 wait/再派，不含「正常推进」。"""
    from agentcore.runtime.coordination.pipeline_view import format_idle_yield_brief
    from agentcore.runtime.runs.types import Deliverable

    live = _plan(
        RunSpec(
            run_id="copy",
            role="内容文案",
            task="写 site/copy.md",
            deliverable=Deliverable(artifacts=["site/copy.md"]),
        ),
        RunSpec(
            run_id="skeleton",
            role="骨架工程师",
            task="写 site/index.html",
            deliverable=Deliverable(artifacts=["site/index.html"]),
            depends_on=["copy"],
        ),
    )
    session = CoordinationSession(
        execution_id="e-idle-pending", total_workers=2, conversation_id="c-idle"
    )
    session.live_plan = live
    session._running_workers["copy"] = "内容文案"
    session._worker_started_at["copy"] = __import__("time").monotonic()
    session.mark_worker_busy("copy", "llm")

    monkeypatch.setattr(
        "agentcore.runtime.interaction_orphan.has_hot_user_pending",
        lambda _cid: True,
    )

    brief = format_idle_yield_brief(session)
    assert "等待用户审批" in brief or "审批/授权" in brief
    assert "正常推进" not in brief
    assert "这是预期中的等待" not in brief
    assert "禁止" in brief or "勿" in brief
    assert "再汇报" in brief
    assert "保持静默，引导" not in brief


async def test_idle_yield_injects_healthy_brief_instead_of_empty(monkeypatch):
    """idle_yield_to_captain 仍按原时机唤醒，但注入进度+无动作导向（不再 injected=0）。"""
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_MAX_S", 1.0)
    clear_active_coordination()
    live = _plan(
        RunSpec(run_id="a", role="内容文案", task="写 site/copy.md", depends_on=[]),
        RunSpec(
            run_id="b",
            role="骨架工程师",
            task="写骨架",
            depends_on=["a"],
        ),
    )
    session = CoordinationSession(execution_id="e-idle-yield", total_workers=2)
    session.live_plan = live
    session._running_workers["a"] = "内容文案"
    session._worker_started_at["a"] = __import__("time").monotonic()
    session.mark_worker_busy("a", "llm")
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        msgs = await asyncio.wait_for(await_coordination_injection([]), timeout=3.0)
        assert len(msgs) == 1
        text = msgs[0].content or ""
        assert "流水线进度" in text
        assert "无需追加" in text or "正常推进" in text
        assert "等待团队事件超时" not in text
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination("e-idle-yield")


async def test_wall_zero_completed_does_not_idle_yield(monkeypatch):
    """coordination=wall 且 completed==0：有 inflight 也不 idle_yield（主回合继续等）。"""
    import contextlib

    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(coord_wait, "_COORD_WAIT_TIMEOUT_MAX_S", 1.0)
    clear_active_coordination()
    live = _plan(
        RunSpec(run_id="a", role="研究员", task="调研", depends_on=[]),
        RunSpec(run_id="b", role="写手", task="撰写", depends_on=[]),
    )
    session = CoordinationSession(
        execution_id="e-wall-hold",
        total_workers=2,
        coordination="wall",
    )
    session.live_plan = live
    session._running_workers["a"] = "研究员"
    session._worker_started_at["a"] = __import__("time").monotonic()
    session.mark_worker_busy("a", "llm")
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)

    async def _complete_later() -> None:
        await asyncio.sleep(0.25)
        from agentcore.runtime.coordination.session import (
            CoordinationEvent,
            CoordinationEventKind,
        )

        session.mark_worker_completed("a")
        session.clear_worker_busy("a")
        session.post(
            CoordinationEvent(
                kind=CoordinationEventKind.WORKER_COMPLETED,
                payload={
                    "run_id": "a",
                    "role": "研究员",
                    "status": "completed",
                    "summary": "ok",
                },
            )
        )

    poster = asyncio.create_task(_complete_later())
    try:
        msgs = await asyncio.wait_for(await_coordination_injection([]), timeout=3.0)
        assert len(msgs) >= 1
        text = "\n".join(m.content or "" for m in msgs)
        # Must have woken on real completion — not the idle_yield「无需追加」brief alone.
        assert "worker_completed" in text or "研究员" in text
        assert "无需追加" not in text
    finally:
        poster.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poster
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination("e-wall-hold")


async def test_merge_all_skipped_returns_structured_failure():
    """整批 run_id 撞车 → success=False，结构化回执列出跳过明细，不改 live 图。"""
    from agentcore.runtime.coordination.host import _merge_into_active_coordination

    clear_active_coordination()
    live = _plan(RunSpec(run_id="a", role="研究员", task="做A"))
    session = CoordinationSession(execution_id="e-skip-all", total_workers=1)
    session.live_plan = live
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        colliding = _plan(
            RunSpec(run_id="a", role="写手", task="撞车同 id"),
        )
        workers_before = session.total_workers
        budget_before = session.budget_remaining
        result = _merge_into_active_coordination(
            _fake_merge_tool(),
            colliding,
            session,
            execution_id="e-skip-all",
            seed_completed=None,
            finalize=False,
            seed_notes=None,
            complexity_hint="",
            call_idx=2,
            completion_criteria=None,
            coordination="none",
        )
        assert result.success is False
        err = result.error or ""
        assert "全部跳过" in err
        assert "`a`" in err
        assert "duplicate run_id" in err
        assert result.contract_failure is True
        assert session.total_workers == workers_before
        assert session.budget_remaining == budget_before
        assert len(live.nodes) == 1
        assert live.nodes[0].role == "研究员"
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination("e-skip-all")


async def test_merge_partial_skip_lists_merged_and_skipped():
    """部分撞车 → success=True，回执同时列已并入与跳过原因；新节点入图。"""
    from agentcore.runtime.coordination.host import _merge_into_active_coordination

    clear_active_coordination()
    live = _plan(RunSpec(run_id="a", role="研究员", task="做A"))
    session = CoordinationSession(execution_id="e-skip-part", total_workers=1)
    session.live_plan = live
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        batch = _plan(
            RunSpec(run_id="a", role="撞车", task="复用 id"),
            RunSpec(run_id="b", role="写手", task="新任务"),
        )
        result = _merge_into_active_coordination(
            _fake_merge_tool(),
            batch,
            session,
            execution_id="e-skip-part",
            seed_completed=None,
            finalize=False,
            seed_notes=None,
            complexity_hint="",
            call_idx=2,
            completion_criteria=None,
            coordination="none",
        )
        assert result.success is True
        out = result.output or ""
        assert "部分跳过" in out
        assert "写手" in out
        assert "`a`" in out
        assert "duplicate run_id" in out
        assert session.total_workers == 2
        assert {n.run_id for n in live.nodes} == {"a", "b"}
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination("e-skip-part")


# --- C: user_stop cascade ---------------------------------------------------


def test_user_stop_body_keeps_stream_without_chrome_notes():
    """Interrupt closer writes captain text only; stop chrome is metadata + UI."""
    body = compose_interrupt_body("partial", reason=TurnInterruptReason.USER_STOP)
    assert body == "partial"
    assert "已停止" not in body
    assert "连接中断" not in body
    empty = compose_interrupt_body("", reason=TurnInterruptReason.USER_STOP)
    assert empty == ""


async def test_user_stop_cancels_drive_and_release_clears():
    clear_active_coordination()
    session = CoordinationSession(
        execution_id="e-stop", total_workers=2, conversation_id="conv-stop"
    )
    session._running_workers["w1"] = "研究员"
    session._running_workers["w2"] = "写手"

    async def _hang() -> None:
        await asyncio.Event().wait()

    session.drive_task = asyncio.create_task(_hang())
    set_active_coordination(session)

    assert cancel_coordination_on_user_stop("conv-stop") is True
    assert session.user_stopped is True
    assert "w1" in session.cancel_ids
    assert "w2" in session.cancel_ids
    # Drive cancel signalled
    await asyncio.sleep(0)
    assert session.drive_task.cancelled() or session.drive_task.done()

    release_turn_coordination("e-stop")
    assert active_coordination("e-stop") is None
    clear_active_coordination()


async def test_turn_runs_stop_cascades_coordination():
    clear_active_coordination()
    conversation_id = "conv-cascade"
    session = CoordinationSession(
        execution_id="e-cascade", total_workers=1, conversation_id=conversation_id
    )
    session._running_workers["w1"] = "研究员"

    async def _hang() -> None:
        await asyncio.Event().wait()

    session.drive_task = asyncio.create_task(_hang())
    set_active_coordination(session)

    async def _noop() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(_noop())
    turn_runs._runs[conversation_id] = TurnRun(
        run_id="r1",
        conversation_id=conversation_id,
        task=task,
        sink=MagicMock(),
    )
    try:
        assert turn_runs.stop(conversation_id) is True
        assert session.user_stopped is True
        assert "w1" in session.cancel_ids
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        turn_runs._runs.pop(conversation_id, None)
        clear_active_coordination()


# --- C3: file ownership at dispatch (完成后仍占 / sibling / replaces) ---


def test_sibling_artifact_cross_detected():
    from agentcore.runtime.coordination.append_guard import find_sibling_artifact_crosses
    from agentcore.runtime.runs.types import Deliverable

    plan = _plan(
        RunSpec(
            run_id="a",
            role="前端",
            task="写 App",
            deliverable=Deliverable(artifacts=["src/App.tsx"]),
        ),
        RunSpec(
            run_id="b",
            role="整合",
            task="也写 App",
            deliverable=Deliverable(artifacts=["src/App.tsx"]),
        ),
    )
    hits = find_sibling_artifact_crosses(plan)
    assert hits
    assert hits[0].reason == "sibling_artifact"


def test_ancestor_artifact_overlap_not_sibling_cross():
    from agentcore.runtime.coordination.append_guard import find_sibling_artifact_crosses
    from agentcore.runtime.runs.types import Deliverable

    plan = _plan(
        RunSpec(
            run_id="up",
            role="草稿",
            task="草稿",
            deliverable=Deliverable(artifacts=["report.md"]),
        ),
        RunSpec(
            run_id="down",
            role="整合",
            task="整合",
            depends_on=["up"],
            deliverable=Deliverable(artifacts=["report.md"]),
        ),
    )
    assert find_sibling_artifact_crosses(plan) == []


def test_completed_owner_blocks_append_file_overlap():
    from agentcore.runtime.coordination.append_guard import (
        declare_plan_artifacts,
        find_append_overlaps,
    )
    from agentcore.runtime.runs.types import Deliverable
    from agentcore.workspace.write_claims import WriteCoordinator

    live = _plan(
        RunSpec(
            run_id="integration",
            role="整合",
            task="写 App.tsx",
            deliverable=Deliverable(artifacts=["App.tsx"]),
        ),
    )
    ownership = WriteCoordinator()
    declare_plan_artifacts(live, ownership)
    # integration finished — still owns App.tsx
    new = _plan(
        RunSpec(
            run_id="fe2",
            role="前端 App",
            task="重写 App",
            deliverable=Deliverable(artifacts=["App.tsx"]),
        )
    )
    hits = find_append_overlaps(
        new, live, completed_run_ids={"integration"}, ownership=ownership
    )
    assert hits
    assert hits[0].reason == "deliverable"
    assert hits[0].live_run_id == "integration"


def test_replaces_skips_overlap_and_transfers():
    from agentcore.runtime.coordination.append_guard import (
        declare_plan_artifacts,
        find_append_overlaps,
    )
    from agentcore.runtime.runs.types import Deliverable
    from agentcore.workspace.write_claims import WriteCoordinator

    live = _plan(
        RunSpec(
            run_id="old",
            role="前端",
            task="写",
            deliverable=Deliverable(artifacts=["App.tsx"]),
        ),
    )
    ownership = WriteCoordinator()
    declare_plan_artifacts(live, ownership)
    assert ownership.owner_of("App.tsx") == "old"

    replacement = _plan(
        RunSpec(
            run_id="new",
            role="前端补派",
            task="接手",
            replaces_run_id="old",
            deliverable=Deliverable(artifacts=["App.tsx"]),
        )
    )
    assert (
        find_append_overlaps(
            replacement, live, completed_run_ids=set(), ownership=ownership
        )
        == []
    )
    declare_plan_artifacts(replacement, ownership)
    assert ownership.owner_of("App.tsx") == "new"


async def test_merge_rejects_after_completed_owner():
    """图全完成后抢终稿仍拒（C3 完成后仍占）。"""
    from agentcore.runtime.coordination.host import _merge_into_active_coordination
    from agentcore.runtime.runs.types import Deliverable
    from agentcore.workspace.write_claims import WriteCoordinator

    clear_active_coordination()
    live = _plan(
        RunSpec(
            run_id="integration",
            role="整合",
            task="写 App.tsx",
            deliverable=Deliverable(artifacts=["App.tsx"]),
        ),
    )
    session = CoordinationSession(execution_id="e-done-own", total_workers=1)
    session.live_plan = live
    session.completed_run_ids.add("integration")
    session.file_ownership = WriteCoordinator()
    from agentcore.runtime.coordination.append_guard import declare_plan_artifacts

    declare_plan_artifacts(live, session.file_ownership)
    session.drive_task = asyncio.create_task(asyncio.sleep(30))
    set_active_coordination(session)
    try:
        result = _merge_into_active_coordination(
            _fake_merge_tool(),
            _plan(
                RunSpec(
                    run_id="fe_dup",
                    role="前端 App",
                    task="再写 App.tsx",
                    deliverable=Deliverable(artifacts=["App.tsx"]),
                )
            ),
            session,
            execution_id="e-done-own",
            seed_completed=None,
            finalize=False,
            seed_notes=None,
            complexity_hint="",
            call_idx=2,
            completion_criteria=None,
            coordination="none",
        )
        assert result.success is False
        assert "重叠" in (result.error or "") or "归属" in (result.error or "")
        assert session.total_workers == 1
    finally:
        session.drive_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await session.drive_task
        clear_active_coordination("e-done-own")


def test_session_ownership_snapshot_roundtrip():
    from agentcore.workspace.write_claims import WriteCoordinator

    session = CoordinationSession(execution_id="e-snap", total_workers=1)
    ledger = session.ensure_file_ownership()
    assert isinstance(ledger, WriteCoordinator)
    ledger.declare("f.md", "w1", frozenset())
    snap = session.snapshot()
    assert snap.file_ownership.get("_v") == 2
    assert snap.file_ownership.get("owners", {}).get("f.md") == "w1"
    restored = CoordinationSession.from_snapshot(snap)
    assert restored.ensure_file_ownership().owner_of("f.md") == "w1"


# --- C3: reject before durable run_plan emit (零图副作用) ---


async def test_sibling_artifact_reject_emits_no_run_plan():
    """同批交付物交叉 → 拒在 emit 前，sink/journal 无该批 run_plan。"""
    from agentcore.runtime.events import EventSink, EventType
    from tests.delegate.conftest import ctx, tool

    clear_active_coordination()
    sink = EventSink()
    t = tool(MagicMock(), sink=sink)
    result = await t.execute(
        {
            "tasks": [
                {
                    "role": "前端",
                    "task": "写 App",
                    "deliverable": {"artifacts": ["src/App.tsx"]},
                },
                {
                    "role": "整合",
                    "task": "也写 App",
                    "deliverable": {"artifacts": ["src/App.tsx"]},
                },
            ],
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is False
    assert result.contract_failure is True
    assert "同批交付物交叉" in (result.error or "") or "交叉" in (result.error or "")
    run_plans = [e for e in sink._history if e.type is EventType.RUN_PLAN]
    assert run_plans == []
    assert active_coordination("e") is None


async def test_sibling_reject_then_reassign_single_swimlane():
    """拒后改分文件再派 → 仅一套泳道（一次成功 run_plan）。"""
    from agentcore.runtime.events import EventSink, EventType
    from tests.delegate.conftest import Provider, ctx, tool

    clear_active_coordination()
    sink = EventSink()
    t = tool(Provider(["AOUT", "BOUT"]), sink=sink)
    rejected = await t.execute(
        {
            "tasks": [
                {
                    "role": "前端",
                    "task": "写 App",
                    "deliverable": {"artifacts": ["src/App.tsx"]},
                },
                {
                    "role": "整合",
                    "task": "也写 App",
                    "deliverable": {"artifacts": ["src/App.tsx"]},
                },
            ],
            "coordinate": False,
        },
        ctx(),
    )
    assert rejected.success is False
    assert [e for e in sink._history if e.type is EventType.RUN_PLAN] == []

    ok = await t.execute(
        {
            "tasks": [
                {
                    "role": "前端",
                    "task": "写 App",
                    "deliverable": {"artifacts": ["src/App.tsx"]},
                },
                {
                    "role": "整合",
                    "task": "写汇总",
                    "deliverable": {"artifacts": ["src/summary.md"]},
                },
            ],
            "coordinate": False,
        },
        ctx(),
    )
    assert ok.success is True
    run_plans = [e for e in sink._history if e.type is EventType.RUN_PLAN]
    assert len(run_plans) == 1
    roles = {a.get("role") for a in (run_plans[0].payload.get("agents") or [])}
    assert "前端" in roles and "整合" in roles


async def test_append_overlap_reject_emits_no_run_plan():
    """活跃协调上文件重叠追加 → 拒在 emit 前，无第二张 run_plan。"""
    from agentcore.runtime.events import EventSink, EventType
    from tests.delegate.conftest import ctx, tool
    from tests.delegate.test_coordination_secondary_delegate import _SlowWorkers

    clear_active_coordination()
    sink = EventSink()
    t = tool(_SlowWorkers(["A", "B", "C"], delay=0.5), sink=sink)
    first = await t.execute(
        {
            "tasks": [
                {
                    "role": "骨架",
                    "task": "写 site/index.html",
                    "deliverable": {
                        "artifacts": ["site/index.html"],
                        "form": "files",
                    },
                },
                {"role": "文案", "task": "写文案"},
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert first.success is True
    session = active_coordination("e")
    assert session is not None
    drive = session.drive_task
    assert drive is not None and not drive.done()
    plans_after_first = [e for e in sink._history if e.type is EventType.RUN_PLAN]
    assert len(plans_after_first) == 1

    second = await t.execute(
        {
            "tasks": [
                {
                    "role": "前端整站",
                    "task": "重写整站",
                    "deliverable": {
                        "artifacts": ["site/index.html"],
                        "form": "files",
                    },
                }
            ],
            "coordinate": True,
        },
        ctx(),
    )
    assert second.success is False
    assert "重叠" in (second.error or "") or "归属" in (second.error or "")
    plans_after_reject = [e for e in sink._history if e.type is EventType.RUN_PLAN]
    assert len(plans_after_reject) == 1
    assert session.total_workers == 2

    drive.cancel()
    with pytest.raises(asyncio.CancelledError):
        await drive
    clear_active_coordination("e")


def test_try_start_sibling_reject_creates_no_session():
    """try_start 防御闸：sibling 拒在建 session 之前。"""
    from agentcore.runtime.coordination.host import try_start_coordination
    from agentcore.runtime.runs.types import Deliverable

    clear_active_coordination()
    plan = _plan(
        RunSpec(
            run_id="a",
            role="前端",
            task="写",
            deliverable=Deliverable(artifacts=["App.tsx"]),
        ),
        RunSpec(
            run_id="b",
            role="整合",
            task="也写",
            deliverable=Deliverable(artifacts=["App.tsx"]),
        ),
    )
    tool = _fake_merge_tool()
    tool._depth = 0
    tool._checkpoint_enabled = False
    started = try_start_coordination(
        tool,
        plan,
        execution_id="e-sib-pre",
        seed_completed=None,
        finalize=False,
        seed_notes=None,
        complexity_hint="standard",
        call_idx=1,
        completion_criteria=None,
        coordinate=True,
    )
    assert started is not None
    assert started.success is False
    assert active_coordination("e-sib-pre") is None


def test_nested_declare_transfers_paths_from_parent_not_all():
    """Nested child artifacts ⊆ parent-owned → path-level handoff; other parent paths stay."""
    from agentcore.runtime.coordination.append_guard import (
        declare_nested_drive_artifacts,
        declare_plan_artifacts,
    )
    from agentcore.runtime.runs.types import Deliverable
    from agentcore.workspace import write_claims as wc
    from agentcore.workspace.write_claims import WriteCoordinator

    parent_plan = _plan(
        RunSpec(
            run_id="backend-fix",
            role="后端补齐",
            task="占位",
            deliverable=Deliverable(
                artifacts=[
                    "src/storage/db.ts",
                    "src/storage/index.ts",
                    "src/tools/base-tool.ts",
                ]
            ),
        )
    )
    ownership = WriteCoordinator()
    declare_plan_artifacts(parent_plan, ownership)
    assert ownership.owner_of("src/storage/db.ts") == "backend-fix"
    assert ownership.owner_of("src/tools/base-tool.ts") == "backend-fix"

    child_plan = _plan(
        RunSpec(
            run_id="storage",
            role="存储层",
            task="写 storage",
            parent_run_id="backend-fix",
            depth=1,
            deliverable=Deliverable(
                artifacts=["src/storage/db.ts", "src/storage/index.ts"]
            ),
        ),
        RunSpec(
            run_id="tools",
            role="工具系统",
            task="写 tools",
            parent_run_id="backend-fix",
            depth=1,
            deliverable=Deliverable(artifacts=["src/tools/base-tool.ts"]),
        ),
    )
    tool = MagicMock()
    tool._depth = 1
    tool._delegate_force = False

    original = wc.resolve_write_coordinator
    wc.resolve_write_coordinator = lambda **_kwargs: ownership  # type: ignore[assignment]
    try:
        conflicts = declare_nested_drive_artifacts(
            tool, child_plan, execution_id="e-nested"
        )
    finally:
        wc.resolve_write_coordinator = original

    assert conflicts == []
    assert ownership.owner_of("src/storage/db.ts") == "storage"
    assert ownership.owner_of("src/storage/index.ts") == "storage"
    assert ownership.owner_of("src/tools/base-tool.ts") == "tools"


def test_nested_declare_skipped_at_depth_zero():
    from agentcore.runtime.coordination.append_guard import declare_nested_drive_artifacts
    from agentcore.runtime.runs.types import Deliverable
    from agentcore.workspace import write_claims as wc
    from agentcore.workspace.write_claims import WriteCoordinator

    ownership = WriteCoordinator()
    ownership.declare("a.md", "lead", frozenset())
    plan = _plan(
        RunSpec(
            run_id="child",
            role="子",
            task="写",
            parent_run_id="lead",
            depth=0,
            deliverable=Deliverable(artifacts=["a.md"]),
        )
    )
    tool = MagicMock()
    tool._depth = 0
    tool._delegate_force = False

    original = wc.resolve_write_coordinator
    wc.resolve_write_coordinator = lambda **_kwargs: ownership  # type: ignore[assignment]
    try:
        conflicts = declare_nested_drive_artifacts(tool, plan, execution_id="e0")
    finally:
        wc.resolve_write_coordinator = original

    assert conflicts == []
    # Depth 0 skipped — ownership unchanged.
    assert ownership.owner_of("a.md") == "lead"
