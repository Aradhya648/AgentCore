"""turn_stream_state repository — Postgres round-trip (流式回复持久化 P0).

Auto-skips when PostgreSQL is unreachable (same fixture as other integration repos).
"""

from uuid import uuid4

from agentcore.db.repositories import TurnStreamStateRepository


async def test_upsert_monotonic_same_generation(session_factory):
    turn_id = str(uuid4())
    channel = "captain:content"
    async with session_factory() as s:
        repo = TurnStreamStateRepository(s)
        assert await repo.upsert(turn_id=turn_id, channel=channel, text="ab", generation=0)
        assert not await repo.upsert(turn_id=turn_id, channel=channel, text="a", generation=0)
        assert await repo.upsert(turn_id=turn_id, channel=channel, text="abc", generation=0)
        rows = await repo.list_for_turn(turn_id)
    assert len(rows) == 1
    assert rows[0].text == "abc"
    assert rows[0].generation == 0


async def test_upsert_generation_reset_clears(session_factory):
    turn_id = str(uuid4())
    channel = "captain:reasoning"
    async with session_factory() as s:
        repo = TurnStreamStateRepository(s)
        assert await repo.upsert(
            turn_id=turn_id, channel=channel, text="thinking…", generation=0
        )
        assert await repo.upsert(turn_id=turn_id, channel=channel, text="", generation=1)
        rows = await repo.list_for_turn(turn_id)
    assert len(rows) == 1
    assert rows[0].text == ""
    assert rows[0].generation == 1


async def test_list_and_delete_for_turn(session_factory):
    turn_id = str(uuid4())
    async with session_factory() as s:
        repo = TurnStreamStateRepository(s)
        await repo.upsert(turn_id=turn_id, channel="captain:content", text="c", generation=0)
        await repo.upsert(turn_id=turn_id, channel="captain:reasoning", text="r", generation=0)
        rows = await repo.list_for_turn(turn_id)
        assert {r.channel for r in rows} == {"captain:content", "captain:reasoning"}
        deleted = await repo.delete_for_turn(turn_id)
        assert deleted == 2
        assert await repo.list_for_turn(turn_id) == []
