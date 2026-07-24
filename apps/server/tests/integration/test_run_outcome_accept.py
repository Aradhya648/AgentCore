"""跑一半改方向 Step 4 · 接受终态收口 (accept-outcome endpoint).

The endpoint records「用户主动接受此结果」onto the SAME append-only delegated-turn audit trail the
run detail already reads — replacing the old frontend-only ``clearExecution``. Owner-scoped
(对话归属防 IDOR) and idempotent per (turn, run).
"""

from uuid import uuid4

import pytest

from agentcore.db.repositories import (
    AgentAuditEventRepository,
    ConversationRepository,
    UserRepository,
)
from tests.integration.conftest import register_and_login


async def _resolve_user_and_conversation(session_factory, username: str, title: str):
    async with session_factory() as session:
        user = await UserRepository(session).get_by_username(username)
        assert user is not None
        conv = await ConversationRepository(session).create(user_id=user.user_id, title=title)
        return user.user_id, conv.id


async def _seed_deterministic_failure(
    session_factory, *, user_id: str, conversation_id: str, turn_id: str, run_id: str
):
    """Seed the BL-6 handling row the run detail keys the accept prompt off of."""
    async with session_factory() as session:
        await AgentAuditEventRepository(session).append(
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            trace_id="trace-accept",
            seq=0,
            category="state",
            action="run.deterministic_failure",
            actor_kind="member",
            outcome="skipped",
            execution_id="exec-accept",
            run_id=run_id,
            detail={"reason": "deterministic"},
        )


@pytest.mark.asyncio
async def test_accept_outcome_records_and_is_idempotent(client, session_factory, make_invite):
    turn_id = str(uuid4())
    run_id = "w1"
    username = f"accept_{uuid4().hex[:8]}"
    invite_code = await make_invite(f"INV-ACCEPT-{uuid4().hex[:6]}")
    await register_and_login(client, invite_code, username)
    user_id, conversation_id = await _resolve_user_and_conversation(
        session_factory, username, "accept idempotent"
    )
    await _seed_deterministic_failure(
        session_factory,
        user_id=user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        run_id=run_id,
    )

    r = await client.post(
        f"/v1/conversations/{conversation_id}/messages/{turn_id}/accept-outcome",
        json={"run_id": run_id, "reason": "deterministic_failure", "execution_id": "exec-accept"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["recorded"] is True

    # The acceptance lands as a run.outcome_accepted row on the turn's audit trail (what the
    # run detail reads to switch from「接受此结果」to「已接受」).
    r_audit = await client.get(
        f"/v1/conversations/{conversation_id}/messages/{turn_id}/audit"
    )
    assert r_audit.status_code == 200, r_audit.text
    accepted = [
        row
        for row in r_audit.json()["data"]
        if row["action"] == "run.outcome_accepted" and row["run_id"] == run_id
    ]
    assert len(accepted) == 1
    assert accepted[0]["outcome"] == "ok"
    assert accepted[0]["detail"]["reason"] == "deterministic_failure"

    # Idempotent: a repeated accept (double-click / retry) is a no-op — no second row.
    r2 = await client.post(
        f"/v1/conversations/{conversation_id}/messages/{turn_id}/accept-outcome",
        json={"run_id": run_id, "reason": "deterministic_failure"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["recorded"] is False

    async with session_factory() as session:
        rows = await AgentAuditEventRepository(session).list_for_turn(
            conversation_id=conversation_id, turn_id=turn_id
        )
    assert sum(1 for r in rows if r.action == "run.outcome_accepted") == 1


@pytest.mark.asyncio
async def test_accept_outcome_redirect_ignored_reason(client, session_factory, make_invite):
    """redirect_ignored trigger: same accept-outcome path, reason recorded on the audit row."""
    turn_id = str(uuid4())
    run_id = "w1"
    username = f"redirect_{uuid4().hex[:8]}"
    invite_code = await make_invite(f"INV-REDIR-{uuid4().hex[:6]}")
    await register_and_login(client, invite_code, username)
    user_id, conversation_id = await _resolve_user_and_conversation(
        session_factory, username, "redirect ignored"
    )
    async with session_factory() as session:
        await AgentAuditEventRepository(session).append(
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            trace_id="trace-redir",
            seq=0,
            category="state",
            action="run.redirect_ignored",
            actor_kind="system",
            outcome="skipped",
            execution_id="exec-redir",
            run_id=run_id,
            detail={"feedback": "改做竞品分析"},
        )

    r = await client.post(
        f"/v1/conversations/{conversation_id}/messages/{turn_id}/accept-outcome",
        json={"run_id": run_id, "reason": "redirect_ignored", "execution_id": "exec-redir"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["recorded"] is True

    r_audit = await client.get(
        f"/v1/conversations/{conversation_id}/messages/{turn_id}/audit"
    )
    accepted = [
        row
        for row in r_audit.json()["data"]
        if row["action"] == "run.outcome_accepted" and row["run_id"] == run_id
    ]
    assert len(accepted) == 1
    assert accepted[0]["detail"]["reason"] == "redirect_ignored"


@pytest.mark.asyncio
async def test_accept_outcome_rejects_non_owner(
    client, new_client, session_factory, make_invite
):
    """IDOR: a user cannot record an accept on someone else's conversation (404, not 200)."""
    turn_id = str(uuid4())
    owner_name = f"owner_{uuid4().hex[:8]}"
    owner_invite = await make_invite(f"INV-OWNER-{uuid4().hex[:6]}")
    await register_and_login(client, owner_invite, owner_name)
    owner_id, conversation_id = await _resolve_user_and_conversation(
        session_factory, owner_name, "owned"
    )
    await _seed_deterministic_failure(
        session_factory,
        user_id=owner_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        run_id="w1",
    )

    async with new_client() as attacker:
        attacker_name = f"attacker_{uuid4().hex[:8]}"
        attacker_invite = await make_invite(f"INV-ATK-{uuid4().hex[:6]}")
        await register_and_login(attacker, attacker_invite, attacker_name)
        r = await attacker.post(
            f"/v1/conversations/{conversation_id}/messages/{turn_id}/accept-outcome",
            json={"run_id": "w1", "reason": "deterministic_failure"},
        )
    assert r.status_code == 404, r.text
