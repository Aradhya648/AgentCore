from uuid import uuid4

from agentcore.db.repositories import UserRepository
from tests.integration.conftest import login_admin
from tests.integration.test_admin_api import (
    _seed_conversation_with_turn,
    _seed_user,
)


async def test_admin_audit_logs_record_and_list(client, make_admin, session_factory):
    """Privileged mutations append audit rows queryable from GET /v1/admin/audit-logs."""
    admin_name, admin_pw = await make_admin()
    async with session_factory() as session:
        users = UserRepository(session)
        target = await users.create(username=f"audit_{uuid4().hex[:8]}", display_name="Audit Target")
        target_id = target.user_id

    await login_admin(client, admin_name, admin_pw)
    r = await client.patch(f"/v1/admin/users/{target_id}", json={"role": "admin"})
    assert r.status_code == 200, r.text

    r = await client.get("/v1/admin/audit-logs")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    row = next(x for x in body["data"] if x["action"] == "user.update")
    assert row["target_type"] == "user"
    assert row["target_id"] == target_id
    assert row["detail"]["role"] == "admin"
    assert row["actor_username"] == admin_name

    r = await client.get("/v1/admin/audit-logs", params={"action": "user.delete"})
    assert r.status_code == 200
    assert all(x["action"] == "user.delete" for x in r.json()["data"])


async def test_admin_replay_view_records_audit(
    client, make_admin, session_factory,
):
    """Reading a conversation replay appends a conversation.replay audit row."""
    admin_name, admin_pw = await make_admin()
    await login_admin(client, admin_name, admin_pw)
    alice = await _seed_user(session_factory, "replay_audit_alice")
    conv_id, _ = await _seed_conversation_with_turn(session_factory, user_id=alice)

    r = await client.get(f"/v1/admin/observability/conversations/{conv_id}")
    assert r.status_code == 200, r.text

    r = await client.get("/v1/admin/audit-logs", params={"action": "conversation.replay"})
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert any(x["target_id"] == conv_id and x["action"] == "conversation.replay" for x in rows)
    row = next(x for x in rows if x["target_id"] == conv_id)
    assert row["target_type"] == "conversation"
    assert row["actor_username"] == admin_name
    assert row["detail"]["owner_user_id"] == alice
