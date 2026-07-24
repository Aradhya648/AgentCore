"""Orphan / fold / audit projector (提问确认交互统一 P1)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agentcore.runtime.audit.projector import project_journal_entry
from agentcore.runtime.interaction import InteractionKind, InteractionRegistry
from agentcore.runtime.interaction_orphan import orphan_registry_pending
from agentcore.runtime.journal.pending_interactions import fold_pending_interactions


@pytest.mark.asyncio
async def test_orphan_registry_hot_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = InteractionRegistry()
    reg.create("a1", "c1", kind=InteractionKind.APPROVAL, payload={"tool_name": "x"})
    reg.create(
        "e-ceo",
        "c1",
        kind=InteractionKind.ESCALATION,
        payload={"awaiting": "ceo"},
    )
    reg.create(
        "e-user",
        "c1",
        kind=InteractionKind.ESCALATION,
        payload={"awaiting": "user"},
    )

    written: list[tuple[str, str]] = []

    async def fake_emit(**kwargs):
        written.append((kwargs["interaction_id"], kwargs["kind"]))

    monkeypatch.setattr(
        "agentcore.runtime.interaction_orphan.emit_orphan_fact",
        fake_emit,
    )
    monkeypatch.setattr(
        "agentcore.runtime.interaction_orphan.default_interaction_registry",
        lambda: reg,
    )

    ids = await orphan_registry_pending("c1", turn_id="t1")
    assert set(ids) == {"a1", "e-user"}
    assert reg.get("e-ceo") is not None
    assert reg.get("a1") is None
    assert ("a1", "approval") in written


def test_projector_accepts_timed_out_and_orphaned() -> None:
    recorder = MagicMock()
    recorder.user_id = "u"
    recorder.conversation_id = "c"
    recorder.turn_id = "t"

    for status in ("timed_out", "orphaned"):
        draft = project_journal_entry(
            recorder,
            {
                "kind": "escalation_resolved",
                "payload": {
                    "escalation_id": "e1",
                    "run_id": "r",
                    "agent_id": "a",
                    "status": status,
                    "answer": "",
                },
            },
        )
        assert draft is not None
        assert draft.outcome == "denied"
        assert draft.action == "escalate.resolved"


def test_fold_three_hot_kinds_all_pending() -> None:
    entries = [
        {
            "kind": "approval_required",
            "payload": {
                "approval_id": "a",
                "conversation_id": "c",
                "tool_call_id": "a",
                "tool_name": "t",
                "arguments": {},
            },
        },
        {
            "kind": "delegation_authorization_required",
            "payload": {
                "authorization_id": "d",
                "conversation_id": "c",
                "execution_id": "e",
                "workers": [],
                "tools": [],
            },
        },
        {
            "kind": "escalation_required",
            "payload": {
                "escalation_id": "e",
                "run_id": "r",
                "agent_id": "a",
                "question": "q",
                "assumption": "x",
            },
        },
    ]
    pending = fold_pending_interactions(entries)
    assert {p.kind for p in pending} == {
        "approval",
        "delegation_authorization",
        "escalation",
    }
