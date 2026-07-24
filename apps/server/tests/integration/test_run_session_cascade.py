"""run_sessions cascade on conversation soft/hard delete."""

from sqlalchemy import select

from agentcore.db.models import RunSessionRow
from agentcore.db.repositories.conversations import ConversationRepository
from agentcore.db.repositories.runs import RunSessionRepository
from tests.integration.conftest import register_and_login


async def test_soft_delete_cascades_run_sessions(client, make_invite, session_factory):
    code = await make_invite("INV-CASCADE-SOFT")
    uid = await register_and_login(client, code, "cascsoft")
    async with session_factory() as s:
        conv = await ConversationRepository(s).create(user_id=uid, title="cascade-soft")
        cid = conv.id
        await RunSessionRepository(s).upsert(
            conversation_id=cid,
            run_id=f"r_soft_{cid[:8]}",
            spec={"run_id": "r"},
            transcript=[],
            content="x",
            recall_count=0,
        )
    async with session_factory() as s:
        assert await ConversationRepository(s).soft_delete(cid, user_id=uid) is True
        left = await s.execute(
            select(RunSessionRow).where(RunSessionRow.conversation_id == cid)
        )
        assert left.scalars().first() is None


async def test_hard_delete_cascades_run_sessions(client, make_invite, session_factory):
    code = await make_invite("INV-CASCADE-HARD")
    uid = await register_and_login(client, code, "caschard")
    async with session_factory() as s:
        conv = await ConversationRepository(s).create(user_id=uid, title="cascade-hard")
        cid = conv.id
        await RunSessionRepository(s).upsert(
            conversation_id=cid,
            run_id=f"r_hard_{cid[:8]}",
            spec={"run_id": "r"},
            transcript=[],
            content="x",
            recall_count=1,
        )
    async with session_factory() as s:
        await ConversationRepository(s).hard_delete(cid)
        left = await s.execute(
            select(RunSessionRow).where(RunSessionRow.conversation_id == cid)
        )
        assert left.scalars().first() is None
