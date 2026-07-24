"""Real-Postgres probe: lv-molihua-trademark tape → turn_journal → reload projection.

Verifies the pure-hydrate path (GET /messages → runs_from_entries) after a real
append-on-emit + pause record + resume + finalize persist — no flush noop.

Evidence for: 「回放结束气泡缺 CEO 总结」是否根因在 hydrate 投影缺 team 后 content 步.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from agentcore.config.paths import PROJECT_ROOT
from agentcore.conversation import store as store_pkg
from agentcore.conversation.store import cloud as cloud_mod
from agentcore.db.repositories import (
    ConversationRepository,
    MessageRepository,
    TurnJournalRepository,
    UserRepository,
)
from agentcore.demo_tape.binding import TapeBinding
from agentcore.demo_tape.player import continue_tape_turn, play_tape_events
from agentcore.runtime import suspension_persistence as persist_mod
from agentcore.runtime.checkpoints import CheckpointDecision, CheckpointResponse
from agentcore.runtime.events import EventSink, FinishReason
from agentcore.runtime.journal.fold import runs_from_entries
from agentcore.runtime.journal.writer import TurnJournalWriter
from agentcore.runtime.pipeline.finalize import _build_runs_payload

TAPE = PROJECT_ROOT / "demos" / "tapes" / "lv-molihua-trademark.json"
# Captain wrap-up heading after the collab graph (tape wording may change round count).
CEO_MARKER = "模拟庭审辩论结果"


def _process_kinds(entries: list[dict]) -> list[str]:
    return [
        str(e.get("kind") or "")
        for e in entries
        if str(e.get("kind") or "").startswith(("process_", "run_process_"))
    ]


def _runs_process_kinds(runs: dict | None) -> list[str]:
    if not runs:
        return []
    return [str(s.get("kind") or "") for s in (runs.get("process") or [])]


def _content_after_team(runs: dict | None) -> list[str]:
    """Texts of content steps that appear after the last team marker in process."""
    if not runs:
        return []
    steps = list(runs.get("process") or [])
    last_team = -1
    for i, s in enumerate(steps):
        if s.get("kind") == "team":
            last_team = i
    if last_team < 0:
        return []
    out: list[str] = []
    for s in steps[last_team + 1 :]:
        if s.get("kind") == "content":
            out.append(str(s.get("text") or ""))
    return out


def _report(label: str, entries: list[dict], runs: dict | None) -> None:
    pk = _process_kinds(entries)
    rk = _runs_process_kinds(runs)
    after = _content_after_team(runs)
    captain_pc = [e for e in entries if e.get("kind") == "process_content"]
    print(f"\n=== {label} ===")
    print(f"turn_journal rows: {len(entries)}")
    print(f"process_*/run_process_* kinds ({len(pk)}): {pk}")
    print(f"process_content count: {len(captain_pc)}")
    for i, e in enumerate(captain_pc):
        text = str((e.get("payload") or {}).get("text") or "")
        print(
            f"  process_content[{i}] len={len(text)} "
            f"has_marker={CEO_MARKER in text} preview={text[:80]!r}"
        )
    print(f"runs.process kinds: {rk}")
    print(f"content steps after team: {len(after)}")
    for i, t in enumerate(after):
        print(
            f"  after_team_content[{i}] len={len(t)} "
            f"has_marker={CEO_MARKER in t} preview={t[:80]!r}"
        )
    print(
        f"VERDICT has_ceo_after_team="
        f"{any(CEO_MARKER in t for t in after)}"
    )


@pytest.mark.asyncio
async def test_lv_molihua_tape_db_hydrate_has_ceo_after_team(
    session_factory, monkeypatch
) -> None:
    if not TAPE.exists():
        pytest.skip(f"tape missing: {TAPE}")

    # Point CloudStore + suspension bridge at the throwaway IT schema.
    monkeypatch.setattr(cloud_mod, "async_session_factory", session_factory)
    monkeypatch.setattr(cloud_mod, "telemetry_session_factory", session_factory)
    monkeypatch.setattr(persist_mod, "async_session_factory", session_factory)
    store_pkg.reset_conversation_store_for_tests()

    mid = str(uuid4())
    trace = "a" * 32

    async with session_factory() as s:
        user = await UserRepository(s).create(
            username=f"tape-{mid[:8]}", display_name="tape"
        )
        uid = user.user_id
        conv = await ConversationRepository(s).create(
            user_id=uid, title="lv-molihua hydrate probe"
        )
        cid = conv.id
        await MessageRepository(s).create(
            conversation_id=cid, role="user", content="搜索并辩论"
        )
        await MessageRepository(s).create_assistant_placeholder(
            conversation_id=cid, message_id=mid, trace_id=trace
        )

    data = json.loads(TAPE.read_text(encoding="utf-8"))
    events = list(data["events"])
    binding = TapeBinding(
        conversation_id=cid,
        tape_path=TAPE,
        speed=500.0,
        max_gap_ms=20,
    )

    saved: list = []

    async def capture_save(suspension):
        await persist_mod.save_paused_turn(suspension)
        saved.append(suspension)

    from agentcore.demo_tape import player as player_mod

    monkeypatch.setattr(player_mod, "save_paused_turn", capture_save)

    # —— Send leg (real flush → real DB append + pause record) ——
    sink = EventSink(conversation_id=cid, message_id=mid)
    writer = TurnJournalWriter(turn_id=mid, conversation_id=cid, trace_id=trace)
    result = await play_tape_events(
        sink=sink,
        events=events,
        start_index=0,
        binding=binding,
        message_id=mid,
        conversation_id=cid,
        user_id=uid,
        user_message="搜索并辩论",
        folder_id=None,
        journal_writer=writer,
        trace_id=trace,
    )
    assert result["finish_reason"] is FinishReason.PAUSED
    assert saved, "pause did not persist suspension"

    async with session_factory() as s:
        entries_pause = await TurnJournalRepository(s).load(mid)
    _report("AFTER_PAUSE", entries_pause, runs_from_entries(entries_pause))

    # —— Resume leg (real flush, no noop) ——
    sink2 = EventSink(conversation_id=cid, message_id=mid)
    result2 = await continue_tape_turn(
        suspension=saved[0],
        response=CheckpointResponse(decision=CheckpointDecision.CONTINUE, note=""),
        sink=sink2,
        folder_id=None,
        trace_id=trace,
    )
    assert result2["finish_reason"] is FinishReason.END_TURN

    async with session_factory() as s:
        entries_pre_fin = await TurnJournalRepository(s).load(mid)
    _report(
        "AFTER_RESUME_FLUSH_BEFORE_FINALIZE",
        entries_pre_fin,
        runs_from_entries(entries_pre_fin),
    )

    # —— Finalize like turn_runner (persist_turn_journal upsert by seq) ——
    backend = MagicMock()
    backend.location = "local"
    backend.dirty = False
    await cloud_mod.CloudStore().finalize(
        mode="cloud",
        result=result2,
        conversation_id=cid,
        user_id=uid,
        folder_id=None,
        backend=backend,
        sink=sink2,
        user_message="搜索并辩论",
        llm_credentials=None,
        trace_id=trace,
        turn_id=mid,
        duration_ms=1,
        kind="turn",
    )

    async with session_factory() as s:
        entries_final = await TurnJournalRepository(s).load(mid)
    runs = runs_from_entries(entries_final)
    _report("AFTER_FINALIZE_RELOAD_PROJECTION", entries_final, runs)

    # Live sink process (control — what the in-memory display had at END_TURN)
    live_kinds = [str(s.get("kind") or "") for s in (sink2.raw_process() or [])]
    live_runs = _build_runs_payload(sink2, FinishReason.END_TURN)
    print("\n=== LIVE_SINK_AT_END ===")
    print(f"raw_process kinds: {live_kinds}")
    print(f"_build_runs_payload process kinds: {_runs_process_kinds(live_runs)}")
    live_after = _content_after_team(live_runs)
    print(
        f"live content after team has_marker="
        f"{any(CEO_MARKER in t for t in live_after)} "
        f"count={len(live_after)}"
    )

    after = _content_after_team(runs)
    has_db = any(CEO_MARKER in t for t in after)
    has_live = any(CEO_MARKER in t for t in live_after)

    # Regression guard (fixed 2026-07-17): the CEO summary content that follows the
    # collaboration graph must be durable in turn_journal so a PURE HYDRATE reload
    # (GET /messages → runs_from_entries) shows it — not only the live sink.
    # Fix: demo_tape.player._result_from_sink now calls sink.flush_process_to_journal()
    # before composing entries, mirroring pipeline.finalize._journal_entries_for_turn,
    # so the open trailing captain content step append-on-emits as process_content.
    print(
        "\n=== FIX_VERIFY ===\n"
        f"reload has CEO content after team: {has_db}\n"
        f"live sink has CEO content after team: {has_live}"
    )
    assert has_live, "control: live sink must show CEO content after team"
    assert has_db, (
        "reload projection must show CEO content after team after flush fix — "
        f"runs.process={_runs_process_kinds(runs)}"
    )
    assert sum(1 for e in entries_final if e.get("kind") == "process_content") == 1
    assert _runs_process_kinds(runs) == ["team", "reasoning", "content"]
