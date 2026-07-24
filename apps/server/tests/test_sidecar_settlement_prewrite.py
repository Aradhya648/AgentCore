"""Sidecar local settlement prewrite (回合恢复状态机收口 · D1)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from agentcore.conversation.store.outbox import OutboxStore, journal_entries_from_map
from agentcore.runtime.suspension import AskUserSuspension
from agentcore.sidecar.paused_store import LocalPausedTurnStore
from agentcore.sidecar.settlement_prewrite import (
    extract_resume_frame_from_entries,
    outbox_has_settlement_for_frame,
    prewrite_sidecar_resume_settlement,
)


def _ask(message_id: str = "m1", conversation_id: str = "c1") -> AskUserSuspension:
    susp = AskUserSuspension(
        message_id=message_id,
        conversation_id=conversation_id,
        user_id="u1",
        captain_run_id="r1",
        checkpoint_id="cp1",
        tool_call_id="tc1",
        base_system_prompt="sys",
        user_message="原始问题",
        transcript=[],
        history=[],
        question="要继续吗？",
        context="背景",
        questions=[
            {
                "id": "q0",
                "prompt": "要继续吗？",
                "kind": "choice",
                "options": ["是", "否"],
                "multiple": False,
                "default": "",
            }
        ],
    )
    susp.journal_entries = [
        {"kind": "checkpoint_required", "payload": {"checkpoint_id": "cp1"}, "ts": None}
    ]
    return susp


@pytest.mark.asyncio
async def test_sidecar_settlement_prewrite_embeds_resume_frame(tmp_path) -> None:
    outbox = OutboxStore(tmp_path / "outbox")
    outbox.bind_turn(
        conversation_id="c1",
        user_message_id="u1",
        user_message="原始问题",
        message_id="m1",
        trace_id="a" * 32,
    )
    await outbox.begin_turn(conversation_id="c1", message_id="m1", trace_id="a" * 32)
    susp = _ask()
    entry = await prewrite_sidecar_resume_settlement(
        outbox,
        susp,
        decision="continue",
        note="ok",
        selected=["是"],
        user_message_id="u1",
        trace_id="a" * 32,
    )
    assert entry["kind"] == "checkpoint_resolved"
    assert entry["payload"]["resume_frame"]["frame"]["checkpoint_id"] == "cp1"
    record = outbox.find_record_by_message_id("m1")
    assert record is not None
    entries = journal_entries_from_map(record.get("journal")) or []
    assert extract_resume_frame_from_entries(entries) is not None
    # Idempotent re-prewrite does not fan out rows.
    await prewrite_sidecar_resume_settlement(
        outbox,
        _ask(),
        decision="continue",
        note="ok",
        selected=["是"],
        user_message_id="u1",
        trace_id="a" * 32,
    )
    record2 = outbox.find_record_by_message_id("m1")
    entries2 = journal_entries_from_map(record2.get("journal")) or []
    resolved = [e for e in entries2 if e.get("kind") == "checkpoint_resolved"]
    assert len(resolved) == 1


def test_recover_stale_claims_consumes_when_settlement_present(tmp_path) -> None:
    paused = tmp_path / "paused"
    outbox_dir = tmp_path / "outbox"
    paused.mkdir()
    outbox_dir.mkdir()
    susp = _ask()
    record = {
        "message_id": "m1",
        "conversation_id": "c1",
        "frame": susp.to_json(),
        "journal_entries": susp.journal_entries,
        "history": [],
        "summary": {},
        "created_at": 0.0,
    }
    (paused / "m1.json.claimed").write_text(json.dumps(record), encoding="utf-8")
    # Seed outbox journal with settlement (D1 prewrite succeeded, crash before confirm).
    outbox_record = {
        "schema_version": 1,
        "user_message_id": "u1",
        "conversation_id": "c1",
        "message_id": "m1",
        "trace_id": "a" * 32,
        "user_message": "q",
        "journal": {
            "0": {
                "kind": "checkpoint_resolved",
                "payload": {
                    "checkpoint_id": "cp1",
                    "decision": "continue",
                    "resume_frame": {"frame": susp.to_json()},
                },
            }
        },
        "phase": "open",
        "updated_at": 1.0,
        "ops": ["settlement_prewrite"],
    }
    (outbox_dir / "u1.json").write_text(json.dumps(outbox_record), encoding="utf-8")

    store = LocalPausedTurnStore(paused, outbox_base=outbox_dir)
    assert not (paused / "m1.json.claimed").exists()
    assert not (paused / "m1.json").exists()  # consumed, not restored

    async def pending() -> list[str]:
        return [s.message_id for s in await store.list_pending("c1")]

    assert asyncio.run(pending()) == []


def test_recover_stale_claims_restores_without_settlement(tmp_path) -> None:
    paused = tmp_path / "paused"
    outbox_dir = tmp_path / "outbox"
    paused.mkdir()
    outbox_dir.mkdir()
    susp = _ask()
    record = {
        "message_id": "m1",
        "conversation_id": "c1",
        "frame": susp.to_json(),
        "journal_entries": [],
        "history": [],
        "summary": {},
        "created_at": 0.0,
    }
    (paused / "m1.json.claimed").write_text(json.dumps(record), encoding="utf-8")
    LocalPausedTurnStore(paused, outbox_base=outbox_dir)
    assert (paused / "m1.json").is_file()
    assert not outbox_has_settlement_for_frame(
        outbox_dir,
        message_id="m1",
        checkpoint_id="cp1",
        suspension_kind="ask_user",
    )


def test_resume_failure_after_prewrite_does_not_restore_frame(tmp_path, monkeypatch) -> None:
    """D1: pipeline crash after settlement confirm must not resurrect the decision card."""
    from agentcore.sidecar import protocol
    from agentcore.sidecar.server import SidecarServer

    async def fake_resume(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("simulated resume crash after settlement")

    monkeypatch.setattr("agentcore.sidecar.server.resume_chat_pipeline", fake_resume)

    sent: list[dict[str, Any]] = []

    async def write_line(line: str) -> None:
        sent.append(json.loads(line))

    server = SidecarServer(write_line)
    data = tmp_path / "data"

    async def drive() -> tuple[list[Any], dict[str, Any]]:
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "userId": "u",
                        "workspaceRoot": str(tmp_path),
                        "dataDir": str(data),
                        "approvalsEnabled": True,
                    },
                }
            )
        )
        assert server._paused_store is not None
        await server._paused_store.save(_ask())
        await server.handle_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "resume",
                    "params": {
                        "messageId": "m1",
                        "conversationId": "c1",
                        "decision": "continue",
                        "note": "",
                        "userMessageId": "u1",
                        "traceId": "a" * 32,
                    },
                }
            )
        )
        await asyncio.gather(*list(server._turns.values()))
        remaining = await server._paused_store.list_pending("c1")
        err = next(m for m in sent if m.get("id") == 9)
        return remaining, err

    remaining, err = asyncio.run(drive())
    assert remaining == []  # frame consumed; not restored
    assert err["error"]["code"] == protocol.INTERNAL_ERROR
