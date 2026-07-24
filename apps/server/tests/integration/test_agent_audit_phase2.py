"""Phase 2 agent audit integration — causal graph, file lookup, retention, cascade."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from agentcore.db.repositories import AgentAuditEventRepository, ConversationRepository
from agentcore.runtime.audit.hooks import bind_recorder, on_delegate_plan, on_journal_fact_appended
from agentcore.runtime.audit.recorder import current_audit_recorder
from agentcore.runtime.audit_retention import run_audit_retention_sweep
from agentcore.runtime.runs import build_run_plan
from tests.integration.conftest import register_and_login


async def _seed_audit_rows(session_factory, *, user_id: str, conversation_id: str, turn_id: str):
    plan, errors = build_run_plan(
        [
            {"id": "w1", "role": "研究员", "task": "调研"},
            {"id": "w2", "role": "写手", "task": "撰写", "depends_on": ["w1"]},
        ],
        valid_tools={"file_write"},
        id_prefix="audit_p2",
    )
    assert not errors

    import agentcore.runtime.audit.recorder as rec_mod

    original = rec_mod.telemetry_session_factory
    rec_mod.telemetry_session_factory = session_factory
    recorder, token = bind_recorder(
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        trace_id="trace-p2",
        captain_run_id="captain-1",
    )
    try:
        on_delegate_plan(execution_id="exec-p2", plan=plan, captain_run_id="captain-1")
        on_journal_fact_appended(
            {
                "kind": "run_context",
                "payload": {
                    "run_id": plan.nodes[1].run_id,
                    "execution_id": "exec-p2",
                    "agent_id": plan.nodes[1].agent_id,
                    "blocks": [
                        {
                            "channel": "dependency",
                            "heading": "前置结果",
                            "body": "upstream output",
                            "chars": 15,
                            "truncated": False,
                            "source_role": "研究员",
                            "source_run_id": plan.nodes[0].run_id,
                            "fidelity": "pass_through",
                            "files": [],
                        }
                    ],
                },
            }
        )
        on_journal_fact_appended(
            {
                "kind": "tool_use_start",
                "payload": {
                    "tool_call_id": "tc-fw",
                    "tool_name": "file_write",
                    "arguments": {"path": "out/report.md"},
                    "run_id": plan.nodes[0].run_id,
                },
            }
        )
        on_journal_fact_appended(
            {
                "kind": "tool_use_end",
                "payload": {
                    "tool_call_id": "tc-fw",
                    "tool_name": "file_write",
                    "status": "success",
                    "run_id": plan.nodes[0].run_id,
                },
            }
        )
        await recorder.flush()
    finally:
        current_audit_recorder.reset(token)
        rec_mod.telemetry_session_factory = original
    return plan


@pytest.mark.asyncio
async def test_turn_audit_include_causal(client, session_factory, make_invite):
    turn_id = str(uuid4())
    username = f"audit_causal_{uuid4().hex[:8]}"
    invite_code = await make_invite(f"INV-AUDIT-CAUSAL-{uuid4().hex[:6]}")
    await register_and_login(client, invite_code, username)

    async with session_factory() as session:
        from agentcore.db.repositories import ConversationRepository, UserRepository

        user = await UserRepository(session).get_by_username(username)
        assert user is not None
        user_id = user.user_id
        conv = await ConversationRepository(session).create(
            user_id=user_id,
            title="audit causal",
        )
        conversation_id = conv.id

    await _seed_audit_rows(
        session_factory,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    r = await client.get(
        f"/v1/conversations/{conversation_id}/messages/{turn_id}/audit",
        params={"include_causal": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 2
    graph = body["causal_graph"]
    assert graph is not None
    kinds = {e["kind"] for e in graph["edges"]}
    assert "parent" in kinds
    assert "depends_on" in kinds
    assert "inject" in kinds


@pytest.mark.asyncio
async def test_file_audit_lookup(client, session_factory, make_invite):
    turn_id = str(uuid4())
    username = f"audit_file_{uuid4().hex[:8]}"
    invite_code = await make_invite(f"INV-AUDIT-FILE-{uuid4().hex[:6]}")
    await register_and_login(client, invite_code, username)

    async with session_factory() as session:
        from agentcore.db.repositories import ConversationRepository, UserRepository

        user = await UserRepository(session).get_by_username(username)
        assert user is not None
        user_id = user.user_id
        conv = await ConversationRepository(session).create(
            user_id=user_id,
            title="audit file",
        )
        conversation_id = conv.id

    await _seed_audit_rows(
        session_factory,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    r = await client.get(
        f"/v1/conversations/{conversation_id}/audit/file",
        params={"path": "out/report.md"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert all(row["target_ref"] == "out/report.md" for row in body["data"])


@pytest.mark.asyncio
async def test_admin_audit_summary(client, make_admin, session_factory):
    admin_name, admin_pw = await make_admin()
    from tests.integration.conftest import login_admin

    await login_admin(client, admin_name, admin_pw)

    turn_id = str(uuid4())
    user_id = str(uuid4())
    async with session_factory() as session:
        from agentcore.db.repositories import ConversationRepository

        conv = await ConversationRepository(session).create(
            user_id=user_id,
            title="admin summary",
        )
        conversation_id = conv.id

    await _seed_audit_rows(
        session_factory,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    r = await client.get("/v1/admin/audit/summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["events"] >= 1
    assert body["delegate_plans"] >= 1
    assert "audit_drops" in body


@pytest.mark.asyncio
async def test_delete_conversation_cascades_audit_rows(session_factory):
    user_id = str(uuid4())
    turn_id = str(uuid4())

    async with session_factory() as session:
        conv = await ConversationRepository(session).create(
            user_id=user_id,
            title="cascade",
        )
        conversation_id = conv.id

    await _seed_audit_rows(
        session_factory,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    async with session_factory() as session:
        repo = AgentAuditEventRepository(session)
        before = await repo.list_for_turn(conversation_id=conversation_id, turn_id=turn_id)
        assert before

        await ConversationRepository(session).hard_delete(conversation_id)
        after = await repo.list_for_turn(conversation_id=conversation_id, turn_id=turn_id)
        assert after == []


@pytest.mark.asyncio
async def test_audit_retention_sweep(session_factory, monkeypatch):
    monkeypatch.setattr(
        "agentcore.runtime.audit_retention.async_session_factory",
        session_factory,
    )
    monkeypatch.setattr("agentcore.runtime.audit_retention.settings.audit_retention_days", 90)

    user_id = str(uuid4())
    turn_id = str(uuid4())

    async with session_factory() as session:
        conv = await ConversationRepository(session).create(
            user_id=user_id,
            title="retention",
        )
        conversation_id = conv.id

    await _seed_audit_rows(
        session_factory,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    async with session_factory() as session:
        from sqlalchemy import update

        from agentcore.db.models import AgentAuditEvent

        stale = datetime.now(UTC) - timedelta(days=120)
        await session.execute(
            update(AgentAuditEvent)
            .where(AgentAuditEvent.turn_id == turn_id)
            .values(created_at=stale)
        )
        await session.commit()

    deleted = await run_audit_retention_sweep()
    assert deleted >= 1

    async with session_factory() as session:
        rows = await AgentAuditEventRepository(session).list_for_turn(
            conversation_id=conversation_id,
            turn_id=turn_id,
        )
        assert rows == []
