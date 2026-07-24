"""Integration: memory watermark backfill (memory/backfill.py).

Backed by real PostgreSQL via ``session_factory`` (auto-skips when none reachable).
"""

from datetime import UTC, datetime

from agentcore.db.repositories import ConversationRepository, UserRepository
from agentcore.memory.backfill import backfill_empty_memory_watermarks
from agentcore.memory.store import CORE_MEMORY_FILE, FileMemoryStore


async def test_backfill_resets_only_empty_memory_users(session_factory, monkeypatch, tmp_path):
    store = FileMemoryStore(tmp_path)
    monkeypatch.setattr(
        "agentcore.memory.backfill.default_memory_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "agentcore.memory.backfill.async_session_factory",
        session_factory,
    )

    async with session_factory() as session:
        users = UserRepository(session)
        convs = ConversationRepository(session)

        empty_user = await users.create(username="backfill_empty", display_name="Empty")
        full_user = await users.create(username="backfill_full", display_name="Full")
        disabled_user = await users.create(username="backfill_off", display_name="Off")
        await users.set_memory_enabled(disabled_user.user_id, False)

        await store.save(full_user.user_id, CORE_MEMORY_FILE, "## 技术栈\n- Rust\n")

        synced_at = datetime(2025, 1, 1, tzinfo=UTC)
        empty_conv = await convs.create(user_id=empty_user.user_id, title="empty chat")
        full_conv = await convs.create(user_id=full_user.user_id, title="full chat")
        off_conv = await convs.create(user_id=disabled_user.user_id, title="off chat")
        for conv_id in (empty_conv.id, full_conv.id, off_conv.id):
            await convs.set_memory_synced_at(conv_id, synced_at)

    stats = await backfill_empty_memory_watermarks(store=store, dry_run=False)

    assert stats.users_scanned == 2  # empty + full; disabled excluded
    assert stats.users_reset == 1
    assert stats.conversations_reset == 1
    assert stats.users_skipped_has_memory == 1

    async with session_factory() as session:
        convs = ConversationRepository(session)
        empty_row = await convs.get_by_id_unscoped(empty_conv.id)
        full_row = await convs.get_by_id_unscoped(full_conv.id)
        off_row = await convs.get_by_id_unscoped(off_conv.id)

    assert empty_row is not None and empty_row.memory_synced_at is None
    assert full_row is not None and full_row.memory_synced_at == synced_at
    assert off_row is not None and off_row.memory_synced_at == synced_at


async def test_backfill_is_idempotent(session_factory, monkeypatch, tmp_path):
    store = FileMemoryStore(tmp_path)
    monkeypatch.setattr(
        "agentcore.memory.backfill.default_memory_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "agentcore.memory.backfill.async_session_factory",
        session_factory,
    )

    async with session_factory() as session:
        users = UserRepository(session)
        convs = ConversationRepository(session)
        user = await users.create(username="backfill_idem", display_name="Idem")
        conv = await convs.create(user_id=user.user_id, title="chat")
        await convs.set_memory_synced_at(conv.id, datetime(2025, 1, 1, tzinfo=UTC))

    first = await backfill_empty_memory_watermarks(store=store, dry_run=False)
    second = await backfill_empty_memory_watermarks(store=store, dry_run=False)

    assert first.users_reset == 1
    assert first.conversations_reset == 1
    assert second.users_reset == 0
    assert second.conversations_reset == 0


async def test_backfill_dry_run_does_not_reset(session_factory, monkeypatch, tmp_path):
    store = FileMemoryStore(tmp_path)
    monkeypatch.setattr(
        "agentcore.memory.backfill.default_memory_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "agentcore.memory.backfill.async_session_factory",
        session_factory,
    )

    synced_at = datetime(2025, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        users = UserRepository(session)
        convs = ConversationRepository(session)
        user = await users.create(username="backfill_dry", display_name="Dry")
        conv = await convs.create(user_id=user.user_id, title="chat")
        await convs.set_memory_synced_at(conv.id, synced_at)

    stats = await backfill_empty_memory_watermarks(store=store, dry_run=True)

    assert stats.users_reset == 1
    assert stats.conversations_reset == 1

    async with session_factory() as session:
        row = await ConversationRepository(session).get_by_id_unscoped(conv.id)

    assert row is not None and row.memory_synced_at == synced_at
