"""TurnState projection + recover_turn + lease sweeper (crash recover).

Pins the single recover primitive: journal → TurnState → seed WaveScheduler
(completed skipped) for crash redrive; resume kinds route through the same path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agentcore.runtime.checkpoints import CheckpointDecision
from agentcore.runtime.events import EventSink
from agentcore.runtime.recover import recover_turn
from agentcore.runtime.runs import RunPlan, RunSpec
from agentcore.runtime.runs.serialize import plan_snapshot_fact, plan_to_json, run_final_fact
from agentcore.runtime.runs.types import RunPhase, RunState
from agentcore.runtime.turn_state import TurnState
from agentcore.tools.protocol import ToolResult


def _plan_two_nodes() -> RunPlan:
    return RunPlan(
        nodes=[
            RunSpec(run_id="w1", task="done", role="研究员"),
            RunSpec(run_id="w2", task="pending", role="写手"),
        ]
    )


def _partial_journal() -> list[dict]:
    """Plan + one completed worker + run_plan execution_id (no turn_end)."""
    plan = _plan_two_nodes()
    completed = RunState(phase=RunPhase.COMPLETED, content="ok")
    snap = plan_snapshot_fact(plan)
    final = run_final_fact("w1", completed)
    return [
        {
            "kind": "run_plan",
            "payload": {"execution_id": "exec-crash-1"},
            "ts": "t0",
            "seq": 0,
        },
        {**snap.entry(), "seq": 1},
        {**final.entry(), "seq": 2},
    ]


def test_turn_state_from_journal_projects_plan_completed_execution_id():
    entries = _partial_journal()
    state = TurnState.from_journal(entries)
    assert state.execution_id == "exec-crash-1"
    assert state.plan is not None
    assert [n.run_id for n in state.plan.nodes] == ["w1", "w2"]
    assert set(state.completed) == {"w1"}
    assert state.completed["w1"].phase is RunPhase.COMPLETED
    assert state.unfinished_run_ids == ["w2"]


def test_turn_state_upto_seq_time_travel():
    entries = _partial_journal()
    # Before the completed fact — no seed yet, both unfinished.
    early = TurnState.from_journal(entries, upto_seq=1)
    assert early.completed == {}
    assert early.plan is not None
    assert early.unfinished_run_ids == ["w1", "w2"]


async def test_recover_turn_crash_redrives_with_seed_completed():
    state = TurnState.from_journal(_partial_journal())
    sink = EventSink()
    seen: dict = {}

    async def _resume_plan(plan, seed_completed, **kwargs):
        seen["plan_ids"] = [n.run_id for n in plan.nodes]
        seen["seed"] = set(seed_completed)
        seen["decision"] = kwargs.get("decision")
        seen["execution_id"] = kwargs.get("execution_id")
        return ToolResult(tool_call_id="t1", success=True, output="redriven")

    delegate = MagicMock()
    delegate.resume_plan = _resume_plan

    settled = await recover_turn(
        state=state,
        sink=sink,
        delegate_tool=delegate,
        execution_id="fresh-should-not-win",
    )
    assert settled.output == "redriven"
    assert settled.terminal_text is None
    assert seen["seed"] == {"w1"}
    assert seen["plan_ids"] == ["w1", "w2"]
    assert seen["decision"] is CheckpointDecision.CONTINUE
    assert seen["execution_id"] == "exec-crash-1"


async def test_recover_turn_resume_plan_review_routes_through_same_primitive():
    from agentcore.runtime.suspension import PlanReviewSuspension

    state = TurnState.from_journal(_partial_journal())
    sink = EventSink()
    seen: dict = {}

    async def _resume_plan(plan, seed_completed, **kwargs):
        seen["seed"] = set(seed_completed)
        seen["decision"] = kwargs.get("decision")
        seen["ceo_review"] = kwargs.get("ceo_review")
        return ToolResult(tool_call_id="t1", success=True, output="resumed")

    delegate = MagicMock()
    delegate.resume_plan = _resume_plan

    review = {
        "conclusion": "可过",
        "risks": ["r"],
        "suggestions": ["s"],
        "source": "llm",
    }
    suspension = PlanReviewSuspension(
        message_id="m1",
        conversation_id="c1",
        user_id="u1",
        captain_run_id="cap1",
        checkpoint_id="cp1",
        tool_call_id="tc1",
        user_message="task",
        base_system_prompt="sys",
        journal_entries=_partial_journal(),
        plan=state.plan or _plan_two_nodes(),
        completed=dict(state.completed),
        steps=[{"run_id": "w1", "role": "研究员", "summary": "…"}],
        pending=[{"run_id": "w2", "role": "写手"}],
        ceo_review=review,
    )

    settled = await recover_turn(
        state=state,
        sink=sink,
        delegate_tool=delegate,
        execution_id="x",
        suspension=suspension,
        decision=CheckpointDecision.CONTINUE,
        note="",
    )
    assert settled.output == "resumed"
    assert seen["seed"] == {"w1"}
    assert seen["decision"] is CheckpointDecision.CONTINUE
    assert seen["ceo_review"] == review


async def test_recover_turn_plan_review_forwards_batch_coordination():
    """plan_review 帧回灌批次协作参数：恢复用全新 DelegateTool（_coordination 缺省
    none），不转发则复核后续波次的 worker 被剥便签三件套。"""
    from agentcore.runtime.suspension import PlanReviewSuspension

    state = TurnState.from_journal(_partial_journal())
    sink = EventSink()
    seen: dict = {}

    async def _resume_plan(plan, seed_completed, **kwargs):
        seen["coordination"] = kwargs.get("coordination")
        seen["team_brief"] = kwargs.get("team_brief")
        return ToolResult(tool_call_id="t1", success=True, output="resumed")

    delegate = MagicMock()
    delegate.resume_plan = _resume_plan

    suspension = PlanReviewSuspension(
        message_id="m1",
        conversation_id="c1",
        user_id="u1",
        captain_run_id="cap1",
        checkpoint_id="cp1",
        tool_call_id="tc1",
        user_message="task",
        base_system_prompt="sys",
        journal_entries=_partial_journal(),
        plan=state.plan or _plan_two_nodes(),
        completed=dict(state.completed),
        steps=[{"run_id": "w1", "role": "研究员", "summary": "…"}],
        coordination="wall",
        team_brief="口径按 v2",
    )
    await recover_turn(
        state=state,
        sink=sink,
        delegate_tool=delegate,
        execution_id="x",
        suspension=suspension,
        decision=CheckpointDecision.CONTINUE,
        note="",
    )
    assert seen["coordination"] == "wall"
    assert seen["team_brief"] == "口径按 v2"


async def test_recover_turn_team_preview_forwards_batch_coordination():
    """开工卡帧回灌批次协作参数（含 seed_notes 补种）——2026-07-20 P2 手驱真跑抓获：
    不转发则 wall 批恢复后降级 none，worker 无便签三件套、CEO 预贴便签丢失。"""
    from agentcore.runtime.suspension import TeamPreviewSuspension

    state = TurnState.from_journal(_partial_journal())
    sink = EventSink()
    seen: dict = {}

    async def _resume_plan(plan, seed_completed, **kwargs):
        seen["coordination"] = kwargs.get("coordination")
        seen["team_brief"] = kwargs.get("team_brief")
        seen["seed_notes"] = kwargs.get("seed_notes")
        seen["coordinate"] = kwargs.get("coordinate")
        return ToolResult(tool_call_id="t1", success=True, output="kicked")

    delegate = MagicMock()
    delegate.resume_plan = _resume_plan

    suspension = TeamPreviewSuspension(
        message_id="m1",
        conversation_id="c1",
        user_id="u1",
        captain_run_id="cap1",
        checkpoint_id="cp1",
        tool_call_id="tc1",
        user_message="task",
        base_system_prompt="sys",
        journal_entries=_partial_journal(),
        plan=state.plan or _plan_two_nodes(),
        workers=[{"run_id": "w1", "role": "研究员", "task": "调研"}],
        coordination="wall",
        team_brief="统一用中文",
        seed_notes=[{"kind": "heads_up", "text": "接口用 REST"}],
    )
    settled = await recover_turn(
        state=state,
        sink=sink,
        delegate_tool=delegate,
        execution_id="x",
        suspension=suspension,
        decision=CheckpointDecision.CONTINUE,
        note="",
    )
    assert settled.output == "kicked"
    assert seen["coordination"] == "wall"
    assert seen["team_brief"] == "统一用中文"
    assert seen["seed_notes"] == [{"kind": "heads_up", "text": "接口用 REST"}]
    assert seen["coordinate"] is True


async def test_sweeper_claims_expired_lease_and_invokes_recover(monkeypatch):
    """Lease + partial journal + no live process → sweeper starts recover with unfinished DAG."""
    from datetime import UTC, datetime, timedelta

    from agentcore.runtime.leases import sweeper as sweeper_mod

    message_id = "11111111-1111-1111-1111-111111111111"
    conversation_id = "22222222-2222-2222-2222-222222222222"
    user_id = "33333333-3333-3333-3333-333333333333"
    entries = _partial_journal()
    expired_row = SimpleNamespace(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id=user_id,
        owner_id="dead-owner",
        phase="running",
        meta={},
        heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
    )
    claimed_row = SimpleNamespace(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id=user_id,
        owner_id="new-owner",
        phase="recovering",
        meta={},
        heartbeat_at=datetime.now(UTC),
    )

    recover_calls: list = []

    async def _fake_recover(lease, state):
        recover_calls.append((lease.message_id, set(state.completed), state.unfinished_run_ids))

    class _FakeLeaseRepo:
        def __init__(self, _session):
            pass

        async def list_expired(self, *, before, limit):
            return [expired_row]

        async def claim_expired(self, mid, *, new_owner_id, before, phase="recovering"):
            assert mid == message_id
            return claimed_row

        async def release(self, mid, *, owner_id=None):
            pass

    class _FakePausedRepo:
        def __init__(self, _session):
            pass

        async def get(self, mid):
            return None

    class _FakeJournalRepo:
        def __init__(self, _session):
            pass

        async def load_owned(self, turn_id, conversation_id):
            return entries

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(sweeper_mod, "TurnLeaseRepository", _FakeLeaseRepo)
    monkeypatch.setattr(sweeper_mod, "PausedTurnRepository", _FakePausedRepo)
    monkeypatch.setattr(sweeper_mod, "TurnJournalRepository", _FakeJournalRepo)
    monkeypatch.setattr(sweeper_mod, "async_session_factory", lambda: _FakeSession())
    monkeypatch.setattr(sweeper_mod.settings, "turn_lease_enabled", True)
    monkeypatch.setattr(
        "agentcore.runtime.recover.recover_expired_lease",
        _fake_recover,
    )

    pending: list = []

    def _capture_task(coro, name=None):
        pending.append(coro)
        return MagicMock()

    monkeypatch.setattr(sweeper_mod.asyncio, "create_task", _capture_task)

    started = await sweeper_mod.run_turn_lease_sweep()
    assert started == 1
    assert len(pending) == 1
    await pending[0]
    assert len(recover_calls) == 1
    mid, completed, unfinished = recover_calls[0]
    assert mid == message_id
    assert completed == {"w1"}
    assert unfinished == ["w2"]


def test_plan_snapshot_round_trip_via_turn_state():
    plan = _plan_two_nodes()
    entries = [{**plan_snapshot_fact(plan).entry()}]
    state = TurnState.from_journal(entries)
    assert plan_to_json(state.plan) == plan_to_json(plan)


async def test_sweeper_claims_orphaned_lease_with_unfinished_dag(monkeypatch):
    """Cancel-path orphan mark (fresh heartbeat) is still reclaimable immediately."""
    from datetime import UTC, datetime

    from agentcore.runtime.leases import sweeper as sweeper_mod

    message_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    conversation_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    user_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    entries = _partial_journal()
    orphaned_row = SimpleNamespace(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id=user_id,
        owner_id="dead-owner",
        phase="orphaned",
        meta={"trace_id": "tr-orphan"},
        heartbeat_at=datetime.now(UTC),  # not TTL-stale — phase drives reclaim
    )
    claimed_row = SimpleNamespace(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id=user_id,
        owner_id="new-owner",
        phase="recovering",
        meta={"trace_id": "tr-orphan"},
        heartbeat_at=datetime.now(UTC),
    )
    recover_calls: list = []

    async def _fake_recover(lease, state):
        recover_calls.append(lease.message_id)

    class _FakeLeaseRepo:
        def __init__(self, _session):
            pass

        async def list_expired(self, *, before, limit):
            return [orphaned_row]

        async def claim_expired(self, mid, *, new_owner_id, before, phase="recovering"):
            return claimed_row

        async def release(self, mid, *, owner_id=None):
            pass

    class _FakePausedRepo:
        def __init__(self, _session):
            pass

        async def get(self, mid):
            return None

    class _FakeJournalRepo:
        def __init__(self, _session):
            pass

        async def load_owned(self, turn_id, conversation_id):
            return entries

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(sweeper_mod, "TurnLeaseRepository", _FakeLeaseRepo)
    monkeypatch.setattr(sweeper_mod, "PausedTurnRepository", _FakePausedRepo)
    monkeypatch.setattr(sweeper_mod, "TurnJournalRepository", _FakeJournalRepo)
    monkeypatch.setattr(sweeper_mod, "async_session_factory", lambda: _FakeSession())
    monkeypatch.setattr(sweeper_mod.settings, "turn_lease_enabled", True)
    monkeypatch.setattr(
        "agentcore.runtime.recover.recover_expired_lease",
        _fake_recover,
    )
    pending: list = []

    def _capture_task(coro, name=None):
        pending.append(coro)
        return MagicMock()

    monkeypatch.setattr(sweeper_mod.asyncio, "create_task", _capture_task)

    started = await sweeper_mod.run_turn_lease_sweep()
    assert started == 1
    await pending[0]
    assert recover_calls == [message_id]


async def test_build_crash_delegate_tool_warns_when_unwired(monkeypatch):
    """未接线必须 warning，禁止静默 info 跳过。"""
    from agentcore.runtime import recover_hooks as hooks
    from tests.conftest import LogSpy

    hooks.set_crash_delegate_factory(None)
    spy = LogSpy()

    def _info_forbidden(event, *args, **kwargs):
        raise AssertionError(f"unwired path must not log at info: {event}")

    spy.info = _info_forbidden  # type: ignore[method-assign]
    monkeypatch.setattr(hooks, "logger", spy)
    lease = SimpleNamespace(
        message_id="m-unwired",
        conversation_id="c-unwired",
    )
    state = TurnState.from_journal(_partial_journal())
    tool = await hooks.build_crash_delegate_tool(lease, state, sink=EventSink())
    assert tool is None
    kw = spy.get("recover.crash_delegate_unwired")
    assert kw["message_id"] == "m-unwired"
    assert kw["unfinished"] == 1
    assert "set_crash_delegate_factory" in kw["hint"]


async def test_recover_expired_lease_degrades_to_interrupted_when_unwired(monkeypatch):
    """Production crash-delegate factory is unwired → honest interrupted, not silent drop."""
    from agentcore.runtime.events import FinishReason
    from agentcore.runtime.recover import recover_expired_lease
    from agentcore.runtime.recover_hooks import set_crash_delegate_factory

    message_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    conversation_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    lease = SimpleNamespace(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id="u1",
        meta={"trace_id": "tr-d"},
        trace_id=None,
    )
    state = TurnState.from_journal(_partial_journal())
    salvage_calls: list[dict] = []
    released: list[str] = []

    async def _fake_orphan(**kwargs):
        return None

    async def _fake_salvage(**kwargs):
        salvage_calls.append(kwargs)
        return True

    async def _fake_release(mid, *, owner_id=None):
        released.append(mid)

    set_crash_delegate_factory(None)
    monkeypatch.setattr(
        "agentcore.runtime.interaction_orphan.orphan_turn_before_recover",
        _fake_orphan,
    )
    monkeypatch.setattr(
        "agentcore.runtime.leases.sweeper.salvage_interrupted_turn",
        _fake_salvage,
    )
    monkeypatch.setattr(
        "agentcore.runtime.leases.service.release_turn_lease",
        _fake_release,
    )

    await recover_expired_lease(lease, state)
    assert len(salvage_calls) == 1
    assert salvage_calls[0]["message_id"] == message_id
    assert salvage_calls[0]["reason"] == "redrive_failed"
    assert released == [message_id]
    # finish_reason constant still the interrupted terminal (salvage path contract)
    assert FinishReason.INTERRUPTED.value == "interrupted"


async def test_recover_expired_lease_redrives_when_factory_wired(monkeypatch):
    """Factory returns a DelegateTool → recover_turn resume_plan runs (true redrive)."""
    from agentcore.runtime.recover import recover_expired_lease
    from agentcore.runtime.recover_hooks import set_crash_delegate_factory

    message_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    conversation_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    lease = SimpleNamespace(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id="u1",
        meta={"trace_id": "tr-r"},
        trace_id=None,
    )
    state = TurnState.from_journal(_partial_journal())
    resume_calls: list[dict] = []
    salvage_calls: list[dict] = []
    released: list[str] = []

    async def _fake_orphan(**kwargs):
        return None

    async def _resume_plan(plan, seed_completed, **kwargs):
        resume_calls.append(
            {
                "plan_ids": [n.run_id for n in plan.nodes],
                "seed": set(seed_completed),
                "execution_id": kwargs.get("execution_id"),
            }
        )
        return ToolResult(tool_call_id="t1", success=True, output="redriven")

    async def _factory(lease_arg, state_arg, *, sink):
        assert lease_arg.message_id == message_id
        assert state_arg.unfinished_run_ids == ["w2"]
        tool = MagicMock()
        tool.resume_plan = _resume_plan
        return tool

    async def _fake_salvage(**kwargs):
        salvage_calls.append(kwargs)
        return True

    async def _fake_release(mid, *, owner_id=None):
        released.append(mid)

    set_crash_delegate_factory(_factory)
    try:
        monkeypatch.setattr(
            "agentcore.runtime.interaction_orphan.orphan_turn_before_recover",
            _fake_orphan,
        )
        monkeypatch.setattr(
            "agentcore.runtime.leases.sweeper.salvage_interrupted_turn",
            _fake_salvage,
        )
        monkeypatch.setattr(
            "agentcore.runtime.leases.service.release_turn_lease",
            _fake_release,
        )
        await recover_expired_lease(lease, state)
    finally:
        set_crash_delegate_factory(None)

    assert len(resume_calls) == 1
    assert resume_calls[0]["seed"] == {"w1"}
    assert resume_calls[0]["plan_ids"] == ["w1", "w2"]
    assert resume_calls[0]["execution_id"] == "exec-crash-1"
    assert salvage_calls == []
    assert released == [message_id]


async def test_recover_expired_lease_salvages_when_rebuild_fails(monkeypatch):
    """Factory rebuild returns None → existing salvage + lease release (no extra fallback)."""
    from agentcore.runtime.recover import recover_expired_lease
    from agentcore.runtime.recover_hooks import set_crash_delegate_factory

    message_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    conversation_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    lease = SimpleNamespace(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id="u1",
        meta={"trace_id": "tr-f"},
        trace_id=None,
    )
    state = TurnState.from_journal(_partial_journal())
    salvage_calls: list[dict] = []
    released: list[str] = []

    async def _fake_orphan(**kwargs):
        return None

    async def _factory_fail(lease_arg, state_arg, *, sink):
        return None

    async def _fake_salvage(**kwargs):
        salvage_calls.append(kwargs)
        return True

    async def _fake_release(mid, *, owner_id=None):
        released.append(mid)

    set_crash_delegate_factory(_factory_fail)
    try:
        monkeypatch.setattr(
            "agentcore.runtime.interaction_orphan.orphan_turn_before_recover",
            _fake_orphan,
        )
        monkeypatch.setattr(
            "agentcore.runtime.leases.sweeper.salvage_interrupted_turn",
            _fake_salvage,
        )
        monkeypatch.setattr(
            "agentcore.runtime.leases.service.release_turn_lease",
            _fake_release,
        )
        await recover_expired_lease(lease, state)
    finally:
        set_crash_delegate_factory(None)

    assert len(salvage_calls) == 1
    assert salvage_calls[0]["message_id"] == message_id
    assert salvage_calls[0]["reason"] == "redrive_failed"
    assert released == [message_id]


async def test_production_crash_factory_returns_none_without_turn_started(monkeypatch):
    """Missing turn_started in journal → rebuild_failed warning + None (salvage upstream)."""
    from agentcore.runtime import crash_delegate as crash_mod
    from agentcore.runtime.crash_delegate import production_crash_delegate_factory
    from tests.conftest import LogSpy

    spy = LogSpy()
    monkeypatch.setattr(crash_mod, "logger", spy)
    lease = SimpleNamespace(
        message_id="m-no-started",
        conversation_id="c-no-started",
        user_id="u1",
    )
    state = TurnState.from_journal(_partial_journal())  # no turn_started
    tool = await production_crash_delegate_factory(lease, state, sink=EventSink())
    assert tool is None
    kw = spy.get("recover.crash_delegate_rebuild_failed")
    assert kw["message_id"] == "m-no-started"
    assert "turn_started" in kw["error"]


async def test_orphan_turn_lease_keeps_row_for_sweeper(monkeypatch):
    """CancelledError path must mark orphaned, not delete the lease row."""
    from agentcore.runtime.leases import service as lease_svc

    calls: list[tuple] = []

    class _FakeRepo:
        def __init__(self, _session):
            pass

        async def mark_orphaned(self, message_id, *, owner_id=None):
            calls.append(("orphan", message_id, owner_id))
            return True

        async def release(self, message_id, *, owner_id=None):
            calls.append(("release", message_id, owner_id))

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(lease_svc, "TurnLeaseRepository", _FakeRepo)
    monkeypatch.setattr(lease_svc, "async_session_factory", lambda: _FakeSession())

    await lease_svc.orphan_turn_lease("m-orphan")
    assert calls[0][0] == "orphan"
    assert calls[0][1] == "m-orphan"
    assert not any(c[0] == "release" for c in calls)
