"""Integration: permission.preset_changed persists via telemetry pool."""

from uuid import uuid4

import pytest

from agentcore.db.repositories import AgentAuditEventRepository
from agentcore.runtime.audit.permission_events import record_permission_preset_change


@pytest.mark.asyncio
async def test_record_permission_preset_change_persists(session_factory, monkeypatch):
    monkeypatch.setattr(
        "agentcore.runtime.audit.permission_events.telemetry_session_factory",
        session_factory,
    )
    user_id = str(uuid4())
    conversation_id = str(uuid4())
    await record_permission_preset_change(
        user_id=user_id,
        conversation_id=conversation_id,
        previous="observe",
        next_preset="workspace",
    )
    async with session_factory() as session:
        rows = await AgentAuditEventRepository(session).list_for_conversation(
            conversation_id=conversation_id
        )
    assert len(rows) == 1
    assert rows[0].action == "permission.preset_changed"
    assert rows[0].category == "permission"
    assert rows[0].detail["previous"] == "observe"
    assert rows[0].detail["permission_preset"] == "workspace"
    assert rows[0].detail["decided_by"] == "user"
