"""Retention cleanup for soft-deleted workspaces (决策⑦: 与软删除对齐).

项目即工作区: aged soft-deleted projects purge their shared ``folder:<id>`` space;
aged soft-deleted 裸聊 conversations purge ``conv:<id>`` scratch. Project-member
conversations never own an independent disk root — deleting the row does not
rmtree the shared project space.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta

from sqlalchemy import update

from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import async_session_factory
from agentcore.db.errors import is_schema_error
from agentcore.db.models import Conversation
from agentcore.db.repositories import ConversationRepository, FolderRepository
from agentcore.workspace.locate import workspace_root_path, workspace_storage_key
from agentcore.workspace.locks import workspace_lock
from agentcore.workspace.snapshots import purge_snapshots

logger = get_logger(__name__)


async def purge_folder_space(*, user_id: str, folder_id: str) -> None:
    """Delete a project's shared workspace directory + snapshots."""
    key = workspace_storage_key(user_id=user_id, folder_id=folder_id, conversation_id="")
    async with workspace_lock(key):
        shutil.rmtree(
            workspace_root_path(user_id=user_id, folder_id=folder_id, conversation_id=""),
            ignore_errors=True,
        )
        await purge_snapshots(user_id=user_id, folder_id=folder_id, conversation_id="")


async def _purge_conversation_space(
    *, user_id: str, conversation_id: str, folder_id: str | None
) -> None:
    """Delete a 裸聊's scratch; project members leave the shared folder space alone."""
    if folder_id:
        return
    key = workspace_storage_key(user_id=user_id, folder_id=None, conversation_id=conversation_id)
    async with workspace_lock(key):
        shutil.rmtree(
            workspace_root_path(user_id=user_id, folder_id=None, conversation_id=conversation_id),
            ignore_errors=True,
        )
        await purge_snapshots(user_id=user_id, folder_id=None, conversation_id=conversation_id)


async def run_retention_sweep() -> dict[str, int]:
    """Purge soft-deleted folders/conversations past the retention period once."""
    if not settings.workspace_retention_enabled:
        return {"folders": 0, "conversations": 0}

    before = datetime.now() - timedelta(days=settings.workspace_retention_days)
    limit = settings.workspace_retention_batch_limit

    async with async_session_factory() as session:
        folders = await FolderRepository(session).list_purgeable(before=before, limit=limit)
    purged_folders = 0
    for folder in folders:
        try:
            await purge_folder_space(user_id=folder.user_id, folder_id=folder.id)
        except Exception as e:
            logger.warning("retention.folder_purge_failed", folder_id=folder.id, error=str(e))
            continue
        async with async_session_factory() as session:
            # Clear membership on any remaining (archived) conversations before
            # the folder row disappears.
            await session.execute(
                update(Conversation)
                .where(Conversation.folder_id == folder.id)
                .values(folder_id=None)
            )
            await session.commit()
            await FolderRepository(session).hard_delete(folder.id)
        purged_folders += 1

    async with async_session_factory() as session:
        conversations = await ConversationRepository(session).list_purgeable(
            before=before, limit=limit
        )
    purged_convs = 0
    for conv in conversations:
        try:
            await _purge_conversation_space(
                user_id=conv.user_id,
                conversation_id=conv.id,
                folder_id=conv.folder_id,
            )
        except Exception as e:
            logger.warning(
                "retention.conversation_purge_failed",
                conversation_id=conv.id,
                error=str(e),
            )
            continue
        async with async_session_factory() as session:
            await ConversationRepository(session).hard_delete(conv.id)
        purged_convs += 1

    return {"folders": purged_folders, "conversations": purged_convs}


async def retention_loop() -> None:
    """Run :func:`run_retention_sweep` forever on the configured interval."""
    interval = settings.workspace_retention_sweep_interval_seconds
    while True:
        try:
            result = await run_retention_sweep()
            if result["folders"] or result["conversations"]:
                logger.info("retention.sweep_purged", **result)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log = logger.error if is_schema_error(e) else logger.warning
            log("retention.sweep_failed", error=str(e))
        await asyncio.sleep(interval)
