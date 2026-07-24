"""Paused-turn durable store — repository + persistence bridge (结构化挂起 2b).

Backed by real PostgreSQL via the ``session_factory`` fixture (auto-skips when none
is reachable). Pins the round trip that makes a plan_review pause survive a
disconnect / restart: upsert-by-message_id, the atomic claim (read-and-delete, so a
turn is never resumed twice), conversation-scoped claim (IDOR-safe), the pending
list for reopen, and the save/claim bridge the pipeline wires for ``/resume``.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import update

from agentcore.config import settings
from agentcore.db.models import PausedTurnRow
from agentcore.db.repositories import PausedTurnRepository, TurnJournalRepository
from agentcore.llm.provider.protocol import LLMMessage, ToolCall, ToolCallFunction
from agentcore.runtime import suspension_persistence as persist_mod
from agentcore.runtime import suspension_retention as retention_mod
from agentcore.runtime.facts import LlmCallFact, RoundBoundaryFact, TurnStartedFact
from agentcore.runtime.journal import window_from_journal
from agentcore.runtime.pipeline.resume.window import resumed_captain_window
from agentcore.runtime.runs import RunPhase, RunPlan, RunSpec, RunState
from agentcore.runtime.suspension import PlanReviewSuspension, suspension_from_json


def _pause_journal_entries() -> list[dict]:
    """A plan_review pause snapshot the suspending face captures (window-rebuildable)."""
    return [
        TurnStartedFact(
            system_prompt="base sys", user_message="原始请求", model_profile="chat"
        )
        .to_fact()
        .entry(),
        RoundBoundaryFact(round_idx=0, run_id="cap1", role="captain").to_fact().entry(),
        LlmCallFact(
            run_id="cap1",
            round_idx=0,
            tool_calls=[
                {
                    "id": "call_del",
                    "type": "function",
                    "function": {"name": "delegate", "arguments": "{}"},
                }
            ],
            finish_reason="tool_calls",
        )
        .to_fact()
        .entry(),
        {
            "kind": "plan_review_required",
            "payload": {"checkpoint_id": "ck1", "steps": [], "pending": []},
            "ts": None,
        },
    ]


def _frame(message_id: str, conversation_id: str, user_id: str) -> PlanReviewSuspension:
    journal_entries = _pause_journal_entries()
    return PlanReviewSuspension(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id=user_id,
        captain_run_id="cap1",
        checkpoint_id="ck1",
        tool_call_id="call_del",
        base_system_prompt="base sys",
        user_message="原始请求",
        transcript=[
            LLMMessage(role="user", content="原始请求"),
            LLMMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_del",
                        function=ToolCallFunction(name="delegate", arguments="{}"),
                    )
                ],
            ),
        ],
        plan=RunPlan(
            nodes=[
                RunSpec(run_id="del_a_1", task="调研", role="研究员"),
                RunSpec(run_id="del_a_2", task="撰写", role="写手", depends_on=["del_a_1"]),
            ]
        ),
        completed={"del_a_1": RunState(phase=RunPhase.COMPLETED, content="S1OUT")},
        journal_entries=journal_entries,
        steps=[{"run_id": "del_a_1", "role": "研究员", "summary": "…"}],
        pending=[{"run_id": "del_a_2", "role": "写手"}],
        trace_id="trace1",
    )


async def _seed_turn_journal(session_factory, frame: PlanReviewSuspension) -> None:
    """Simulate append-on-emit: facts already in ``turn_journal`` before pause save."""
    async with session_factory() as s:
        await TurnJournalRepository(s).record(
            turn_id=frame.message_id,
            conversation_id=frame.conversation_id,
            trace_id=frame.trace_id,
            entries=frame.journal_entries,
        )


async def test_upsert_then_claim_round_trips(session_factory):
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    frame = _frame(mid, cid, uid)
    async with session_factory() as s:
        await PausedTurnRepository(s).upsert(
            message_id=mid,
            conversation_id=cid,
            user_id=uid,
            frame=frame.to_json(),
            trace_id="trace1",
        )

    async with session_factory() as s:
        row = await PausedTurnRepository(s).claim(mid, conversation_id=cid)
    assert row is not None
    restored = suspension_from_json(row.frame)
    assert isinstance(restored, PlanReviewSuspension)
    assert restored.tool_call_id == "call_del"
    # NEITHER ``plan`` NOR ``completed`` is serialized into the frame (执行级事件溯源 Phase 2) —
    # both are re-projected from the journal's plan_snapshot / run-final facts on resume, so a
    # claimed frame carries an empty plan placeholder + no completed.
    assert restored.plan.nodes == []
    assert restored.completed == {}

    # Claimed once → gone (a second claim sees nothing).
    async with session_factory() as s:
        again = await PausedTurnRepository(s).claim(mid, conversation_id=cid)
    assert again is None


async def test_upsert_overwrites_in_place(session_factory):
    # Re-pausing the same turn (resume → pause again) overwrites the frame, not a 2nd row.
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    async with session_factory() as s:
        repo = PausedTurnRepository(s)
        await repo.upsert(message_id=mid, conversation_id=cid, user_id=uid, frame={"v": 1})
        await repo.upsert(message_id=mid, conversation_id=cid, user_id=uid, frame={"v": 2})

    async with session_factory() as s:
        rows = await PausedTurnRepository(s).list_pending(cid)
    assert len(rows) == 1
    assert rows[0].frame == {"v": 2}


async def test_claim_scoped_to_conversation_is_idor_safe(session_factory):
    # A claim scoped to the WRONG conversation must neither return nor delete the frame.
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    async with session_factory() as s:
        await PausedTurnRepository(s).upsert(
            message_id=mid, conversation_id=cid, user_id=uid, frame={"v": 1}
        )

    async with session_factory() as s:
        wrong = await PausedTurnRepository(s).claim(mid, conversation_id=str(uuid4()))
    assert wrong is None

    # Still claimable within its real conversation (it was not deleted).
    async with session_factory() as s:
        right = await PausedTurnRepository(s).claim(mid, conversation_id=cid)
    assert right is not None


async def test_list_pending_oldest_first(session_factory):
    cid, uid = str(uuid4()), str(uuid4())
    m1, m2 = str(uuid4()), str(uuid4())
    async with session_factory() as s:
        repo = PausedTurnRepository(s)
        await repo.upsert(message_id=m1, conversation_id=cid, user_id=uid, frame={"n": 1})
        await repo.upsert(message_id=m2, conversation_id=cid, user_id=uid, frame={"n": 2})

    async with session_factory() as s:
        rows = await PausedTurnRepository(s).list_pending(cid)
    assert [r.message_id for r in rows] == [m1, m2]  # created order (oldest first)


async def test_delete_removes_frame(session_factory):
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    async with session_factory() as s:
        await PausedTurnRepository(s).upsert(
            message_id=mid, conversation_id=cid, user_id=uid, frame={"v": 1}
        )
    async with session_factory() as s:
        await PausedTurnRepository(s).delete(mid)
    async with session_factory() as s:
        rows = await PausedTurnRepository(s).list_pending(cid)
    assert rows == []


async def test_save_claim_bridge_round_trips(session_factory, monkeypatch):
    # The bridge uses async_session_factory directly → repoint it at the test schema.
    monkeypatch.setattr(persist_mod, "async_session_factory", session_factory)
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    frame = _frame(mid, cid, uid)

    await persist_mod.save_paused_turn(frame)

    # Listed as pending before it is claimed.
    pending = await persist_mod.list_paused_turns(cid)
    assert [f.message_id for f in pending] == [mid]

    # journal_entries ride on save_paused_turn's turn_journal snapshot (唯一事实源).
    async with session_factory() as s:
        entries = await TurnJournalRepository(s).load(mid)
    assert [e["kind"] for e in entries] == [
        "turn_started",
        "round_boundary",
        "llm_call",
        "plan_review_required",
    ]

    claimed = await persist_mod.claim_paused_turn(mid, conversation_id=cid)
    assert claimed is not None
    assert claimed.message_id == mid
    assert claimed.user_message == "原始请求"
    # transcript / completed / plan are NOT serialized into the frame (执行级事件溯源 Phase 2
    # ⑤/⑥ + plan 退场) — resume rebuilds the CEO window, re-seeds finished workers, AND
    # rebuilds the DAG from turn_journal; only the suspended call id survives (tool_call_id).
    assert claimed.transcript == []
    assert claimed.completed == {}
    assert claimed.plan.nodes == []
    assert claimed.tool_call_id == "call_del"
    # The journal-so-far is re-hydrated from turn_journal (唯一事实源, not the frame): the
    # display ``journal`` (resume seed) AND the raw ``journal_entries`` (the window source
    # _resumed_captain_window folds) both come back, so resume replays the pre-pause graph.
    assert any(e.get("type") == "plan_review_required" for e in claimed.journal)
    assert [e["kind"] for e in claimed.journal_entries] == [
        "turn_started",
        "round_boundary",
        "llm_call",
        "plan_review_required",
    ]

    # Claimed → no longer pending, and a re-claim misses (atomic once).
    assert await persist_mod.list_paused_turns(cid) == []
    assert await persist_mod.claim_paused_turn(mid, conversation_id=cid) is None


async def test_save_paused_turn_persists_journal_snapshot_without_prior_db_rows(
    session_factory, monkeypatch
):
    """Regression: pause save must snapshot journal_entries even when append-on-emit missed."""
    monkeypatch.setattr(persist_mod, "async_session_factory", session_factory)
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    frame = _frame(mid, cid, uid)

    # No _seed_turn_journal — simulates append-on-emit never landing before pause.
    await persist_mod.save_paused_turn(frame)

    async with session_factory() as s:
        entries = await TurnJournalRepository(s).load(mid)
    assert entries
    assert entries[0]["kind"] == "turn_started"
    assert window_from_journal(entries) is not None

    claimed = await persist_mod.claim_paused_turn(mid, conversation_id=cid)
    assert claimed is not None
    assert claimed.transcript == []
    window = resumed_captain_window(claimed, history=[])
    assert window is not None
    assert window[-1].tool_calls[0].function.name == "delegate"


async def test_delete_bridge_drops_frame(session_factory, monkeypatch):
    monkeypatch.setattr(persist_mod, "async_session_factory", session_factory)
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    await persist_mod.save_paused_turn(_frame(mid, cid, uid))
    await persist_mod.delete_paused_turn(mid)
    assert await persist_mod.claim_paused_turn(mid, conversation_id=cid) is None


async def test_restore_paused_turn_after_claim_allows_retry(session_factory, monkeypatch):
    """Cloud resume failure parity: claim deletes the row; restore puts it back for retry."""
    monkeypatch.setattr(persist_mod, "async_session_factory", session_factory)
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())
    frame = _frame(mid, cid, uid)
    await persist_mod.save_paused_turn(frame)

    claimed = await persist_mod.claim_paused_turn(mid, conversation_id=cid)
    assert claimed is not None
    assert await persist_mod.list_paused_turns(cid) == []
    assert await persist_mod.claim_paused_turn(mid, conversation_id=cid) is None

    await persist_mod.restore_paused_turn(claimed)

    pending = await persist_mod.list_paused_turns(cid)
    assert [f.message_id for f in pending] == [mid]
    again = await persist_mod.claim_paused_turn(mid, conversation_id=cid)
    assert again is not None
    assert again.message_id == mid
    assert again.checkpoint_id == "ck1"
    # turn_journal survived the first claim; re-claim still re-hydrates it.
    assert [e["kind"] for e in again.journal_entries] == [
        "turn_started",
        "round_boundary",
        "llm_call",
        "plan_review_required",
    ]


async def test_retention_sweep_prunes_aged_and_batches(session_factory, monkeypatch):
    monkeypatch.setattr(retention_mod, "async_session_factory", session_factory)
    monkeypatch.setattr(settings, "structured_suspension_persist_enabled", True)
    monkeypatch.setattr(settings, "paused_turn_retention_days", 7)
    # batch limit 2 with 3 aged rows → the loop must do >1 round to clear them all.
    monkeypatch.setattr(settings, "paused_turn_sweep_batch_limit", 2)
    cid, uid = str(uuid4()), str(uuid4())
    aged_ids = [str(uuid4()) for _ in range(3)]
    fresh_id = str(uuid4())

    async with session_factory() as s:
        repo = PausedTurnRepository(s)
        for mid in (*aged_ids, fresh_id):
            await repo.upsert(message_id=mid, conversation_id=cid, user_id=uid, frame={"v": 1})

    # Age the three past the 7-day window; leave `fresh` at now().
    aged = datetime.now(UTC) - timedelta(days=10)
    async with session_factory() as s:
        await s.execute(
            update(PausedTurnRow)
            .where(PausedTurnRow.message_id.in_(aged_ids))
            .values(updated_at=aged)
        )
        await s.commit()

    deleted = await retention_mod.run_paused_turn_retention_sweep()

    assert deleted == 3  # all aged rows, cleared across multiple batches
    async with session_factory() as s:
        survivors = await PausedTurnRepository(s).list_pending(cid)
    assert [r.message_id for r in survivors] == [fresh_id]  # recently-touched kept


async def test_retention_sweep_noop_when_disabled(session_factory, monkeypatch):
    monkeypatch.setattr(retention_mod, "async_session_factory", session_factory)
    monkeypatch.setattr(settings, "structured_suspension_persist_enabled", False)
    assert await retention_mod.run_paused_turn_retention_sweep() == 0


async def test_retention_sweep_clears_orphan_turn_journal(session_factory, monkeypatch):
    # An abandoned pause's journal-so-far lives in turn_journal (唯一事实源) but never
    # produced a message to project onto; the sweep that prunes the frame must clear
    # the otherwise-orphan journal rows too.
    monkeypatch.setattr(persist_mod, "async_session_factory", session_factory)
    monkeypatch.setattr(retention_mod, "async_session_factory", session_factory)
    monkeypatch.setattr(settings, "structured_suspension_persist_enabled", True)
    monkeypatch.setattr(settings, "paused_turn_retention_days", 7)
    mid, cid, uid = str(uuid4()), str(uuid4()), str(uuid4())

    frame = _frame(mid, cid, uid)
    await _seed_turn_journal(session_factory, frame)
    await persist_mod.save_paused_turn(frame)
    async with session_factory() as s:
        assert await TurnJournalRepository(s).load(mid)  # journal landed before pause save

    # Age the frame past the window, then sweep.
    aged = datetime.now(UTC) - timedelta(days=10)
    async with session_factory() as s:
        await s.execute(
            update(PausedTurnRow).where(PausedTurnRow.message_id == mid).values(updated_at=aged)
        )
        await s.commit()
    deleted = await retention_mod.run_paused_turn_retention_sweep()

    assert deleted == 1
    # Both the frame AND its orphan journal are gone.
    async with session_factory() as s:
        assert await PausedTurnRepository(s).list_pending(cid) == []
        assert await TurnJournalRepository(s).load(mid) == []
