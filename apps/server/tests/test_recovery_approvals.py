"""Recovery pending_interactions (提问确认交互统一 P1)."""

from __future__ import annotations

from agentcore.runtime.journal.pending_interactions import fold_pending_interactions


def test_recovery_fold_payload_is_required_wire_verbatim() -> None:
    required_payload = {
        "approval_id": "call-1",
        "conversation_id": "conv-a",
        "tool_call_id": "call-1",
        "tool_name": "file_write",
        "arguments": {"path": "/tmp/x.txt"},
    }
    entries = [{"kind": "approval_required", "payload": required_payload}]
    pending = fold_pending_interactions(entries, message_id="msg-1")
    assert len(pending) == 1
    assert pending[0].payload == required_payload
    assert pending[0].kind == "approval"
    assert pending[0].id == "call-1"
    assert pending[0].message_id == "msg-1"
