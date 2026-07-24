"""Integration test for the retention sweep (决策⑦), backed by real PostgreSQL.

Auto-skips when no PostgreSQL is reachable (via ``session_factory``). The sweep
uses ``async_session_factory`` directly (not the request-scoped ``get_db``), so it
is repointed at the test schema here; ``data_dir`` + storage are redirected to a
tmp dir so the purge only touches throwaway files.

项目即工作区: aged soft-deleted projects purge shared ``folder:<id>`` space;
aged soft-deleted 裸聊 purge ``conv:<id>``; project-member conversation rows do
not rmtree the shared project root.
"""

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update

from agentcore.config import settings
from agentcore.db.models import Conversation, Folder
from agentcore.db.repositories import (
    ConversationRepository,
    FolderRepository,
    UserRepository,
)
from agentcore.storage.factory import build_storage_provider
from agentcore.workspace import retention as retention_mod
from agentcore.workspace.locate import resolve_workspace_root, workspace_root_path
from agentcore.workspace.snapshots import create_snapshot


def _seed_space(uid: str, folder_id: str | None, conv_id: str) -> None:
    root = resolve_workspace_root(user_id=uid, folder_id=folder_id, conversation_id=conv_id)
    (root / "file.txt").write_text("data", encoding="utf-8")


async def test_retention_sweep_purges_aged_soft_deletes(
    session_factory, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(retention_mod, "async_session_factory", session_factory)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "filesystem")
    monkeypatch.setattr(settings, "workspace_retention_days", 30)
    build_storage_provider.cache_clear()

    aged = datetime.now() - timedelta(days=40)

    async with session_factory() as s:
        uid = (await UserRepository(s).create(username="ret", display_name="ret")).user_id

    async with session_factory() as s:
        folder_a = await FolderRepository(s).create(user_id=uid, name="A")
        folder_b = await FolderRepository(s).create(user_id=uid, name="B")
    fa, fb = folder_a.id, folder_b.id

    async with session_factory() as s:
        repo = ConversationRepository(s)
        # Born into project B (shared folder space).
        grouped = await repo.create(user_id=uid, title="grouped", folder_id=fb)
        grouped_alive = await repo.create(user_id=uid, title="grouped-alive", folder_id=fb)
        ungrouped = await repo.create(user_id=uid, title="ungrouped")
        recent = await repo.create(user_id=uid, title="recent")
    gid, gaid, ugid, rid = grouped.id, grouped_alive.id, ungrouped.id, recent.id

    _seed_space(uid, fb, gid)  # shared project root
    _seed_space(uid, None, ugid)
    await create_snapshot(user_id=uid, folder_id=fb, conversation_id=gid)
    await create_snapshot(user_id=uid, folder_id=None, conversation_id=ugid)

    async with session_factory() as s:
        await FolderRepository(s).soft_delete(fa, user_id=uid)
        cr = ConversationRepository(s)
        await cr.soft_delete(gid, user_id=uid)
        await cr.soft_delete(ugid, user_id=uid)
        await cr.soft_delete(rid, user_id=uid)

    async with session_factory() as s:
        await s.execute(update(Folder).where(Folder.id == fa).values(deleted_at=aged))
        await s.execute(
            update(Conversation).where(Conversation.id.in_([gid, ugid])).values(deleted_at=aged)
        )
        await s.commit()

    result = await retention_mod.run_retention_sweep()

    assert result["folders"] == 1
    assert result["conversations"] == 2

    async with session_factory() as s:
        folders = (await s.execute(select(Folder.id))).scalars().all()
        convs = (await s.execute(select(Conversation.id))).scalars().all()

    assert fa not in folders
    assert fb in folders
    assert gid not in convs and ugid not in convs
    assert rid in convs and gaid in convs

    # Soft-deleted project member did NOT rmtree the shared project space (sibling alive).
    assert workspace_root_path(user_id=uid, folder_id=fb, conversation_id=gaid).exists()
    assert not workspace_root_path(user_id=uid, folder_id=None, conversation_id=ugid).exists()

    build_storage_provider.cache_clear()
