"""Journal writer degradation marks paused frames."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agentcore.runtime.journal.writer import TurnJournalWriter, current_journal_writer
from agentcore.runtime.suspension import AskUserSuspension, SuspensionKind
from agentcore.runtime.suspension_persistence import save_paused_turn


def _ask_user_suspension() -> AskUserSuspension:
    return AskUserSuspension(
        message_id="msg-1",
        conversation_id="conv-1",
        user_id="user-1",
        captain_run_id="run-1",
        checkpoint_id="cp-1",
        tool_call_id="tc-1",
        base_system_prompt="sys",
        user_message="hello",
        question="pick one",
    )


@pytest.mark.asyncio
async def test_save_paused_turn_records_journal_snapshot() -> None:
    """Pause save must write journal_entries to turn_journal, not only flush the writer."""
    suspension = _ask_user_suspension()
    suspension.journal_entries = [
        {"kind": "turn_started", "payload": {"user_message": "hello"}, "ts": None},
        {"kind": "checkpoint_required", "payload": {"checkpoint_id": "cp-1"}, "ts": None},
    ]
    with patch(
        "agentcore.runtime.suspension_persistence.async_session_factory"
    ) as factory:
        session = AsyncMock()
        factory.return_value.__aenter__.return_value = session
        with patch(
            "agentcore.runtime.suspension_persistence.PausedTurnRepository"
        ) as repo_cls, patch(
            "agentcore.runtime.suspension_persistence.TurnJournalRepository"
        ) as journal_cls:
            repo_cls.return_value.upsert = AsyncMock()
            journal_cls.return_value.record = AsyncMock()
            with patch(
                "agentcore.runtime.suspension_persistence._notify_pause",
                AsyncMock(),
            ):
                await save_paused_turn(suspension)
    journal_cls.return_value.record.assert_awaited_once_with(
        turn_id="msg-1",
        conversation_id="conv-1",
        trace_id=None,
        entries=suspension.journal_entries,
    )


@pytest.mark.asyncio
async def test_save_paused_turn_marks_degraded_when_writer_failed() -> None:
    suspension = _ask_user_suspension()
    writer = TurnJournalWriter(
        turn_id="msg-1",
        conversation_id="conv-1",
        trace_id="trace-1",
    )
    writer._degraded = True  # noqa: SLF001 — simulate append failures
    token = current_journal_writer.set(writer)
    try:
        with patch(
            "agentcore.runtime.suspension_persistence.async_session_factory"
        ) as factory:
            session = AsyncMock()
            factory.return_value.__aenter__.return_value = session
            with patch(
                "agentcore.runtime.suspension_persistence.PausedTurnRepository"
            ) as repo_cls:
                repo_cls.return_value.upsert = AsyncMock()
                with patch(
                    "agentcore.runtime.suspension_persistence._notify_pause",
                    AsyncMock(),
                ):
                    await save_paused_turn(suspension)
    finally:
        current_journal_writer.reset(token)
    assert suspension.journal_degraded is True
    frame = repo_cls.return_value.upsert.await_args.kwargs["frame"]
    assert frame["journal_degraded"] is True
    assert frame["kind"] == SuspensionKind.ASK_USER.value
    assert writer.sealed is True


@pytest.mark.asyncio
async def test_save_paused_turn_seals_writer_after_persist() -> None:
    """Successful pause save seals the append-on-emit writer (hard boundary)."""
    suspension = _ask_user_suspension()
    suspension.journal_entries = [
        {"kind": "checkpoint_required", "payload": {"checkpoint_id": "cp-1"}, "ts": None},
    ]
    writer = TurnJournalWriter(
        turn_id="msg-1",
        conversation_id="conv-1",
        trace_id="trace-1",
        initial_seq=3,
    )
    token = current_journal_writer.set(writer)
    try:
        with patch(
            "agentcore.runtime.suspension_persistence.async_session_factory"
        ) as factory:
            session = AsyncMock()
            factory.return_value.__aenter__.return_value = session
            with patch(
                "agentcore.runtime.suspension_persistence.PausedTurnRepository"
            ) as repo_cls, patch(
                "agentcore.runtime.suspension_persistence.TurnJournalRepository"
            ) as journal_cls:
                repo_cls.return_value.upsert = AsyncMock()
                journal_cls.return_value.record = AsyncMock()
                with patch(
                    "agentcore.runtime.suspension_persistence._notify_pause",
                    AsyncMock(),
                ):
                    await save_paused_turn(suspension)
        assert writer.sealed is True
        assert writer.next_seq == 3
        assert writer.schedule_append({"kind": "post_pause"}) is None
    finally:
        current_journal_writer.reset(token)


@pytest.mark.asyncio
async def test_save_paused_turn_raises_and_does_not_seal_on_persist_failure() -> None:
    """D11：persist 失败必须抛出；writer 不得 seal（避免假 PAUSED）。"""
    suspension = _ask_user_suspension()
    writer = TurnJournalWriter(
        turn_id="msg-1",
        conversation_id="conv-1",
        trace_id="trace-1",
    )
    token = current_journal_writer.set(writer)
    try:
        with patch(
            "agentcore.runtime.suspension_persistence.async_session_factory"
        ) as factory:
            factory.return_value.__aenter__.side_effect = RuntimeError("db down")
            with patch(
                "agentcore.runtime.suspension_persistence._notify_pause",
                AsyncMock(),
            ), pytest.raises(RuntimeError, match="db down"):
                await save_paused_turn(suspension)
        assert writer.sealed is False
    finally:
        current_journal_writer.reset(token)


def test_resumed_captain_window_raises_on_journal_degraded() -> None:
    from agentcore.core.errors import ResumeJournalDegradedError
    from agentcore.runtime.pipeline.resume.window import resumed_captain_window

    suspension = _ask_user_suspension()
    suspension.journal_degraded = True
    with pytest.raises(ResumeJournalDegradedError, match="执行日志保存失败"):
        resumed_captain_window(suspension, history=[])
