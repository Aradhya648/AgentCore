"""Immediate permanent project wipe (彻底删除项目).

Hard-deletes every member conversation (cascade messages / runs / journal / …),
purges the shared cloud ``folder:<id>`` workspace directory + server snapshots,
unbinds boards (same soft-delete rule: boards fall back to ungrouped, not deleted),
then removes the folder row.

Local-mode projects bind a user OS directory: this path never touches that
directory — only DB rows and server-side workspace data are cleared.
"""

from __future__ import annotations

from sqlalchemy import update

from agentcore.db.base import async_session_factory
from agentcore.db.models import Board
from agentcore.db.repositories import (
    ConversationRepository,
    ConversationShareRepository,
    FolderRepository,
)
from agentcore.workspace import grant_store
from agentcore.workspace.retention import purge_folder_space


async def permanent_delete_folder(*, folder_id: str, user_id: str) -> bool:
    """Wipe a live project: member chats, cloud space/snapshots, then the folder row."""
    async with async_session_factory() as session:
        folder_repo = FolderRepository(session)
        conv_repo = ConversationRepository(session)
        folder = await folder_repo.get_by_id(folder_id, user_id=user_id)
        if not folder:
            return False
        conv_ids = await conv_repo.list_ids_by_folder(folder_id, user_id=user_id)

    async with async_session_factory() as session:
        conv_repo = ConversationRepository(session)
        share_repo = ConversationShareRepository(session)
        for conversation_id in conv_ids:
            await share_repo.revoke_all_for_conversation(conversation_id)
            await grant_store.clear_conversation(conversation_id)
            from agentcore.runtime.browser import default_browser_session_registry
            from agentcore.workspace import organize_journal, organize_plan_store

            organize_plan_store.clear_conversation(conversation_id)
            organize_journal.clear_conversation(conversation_id)
            # L3 team-browser: cascade-close any live sandbox session (no-op when absent).
            await default_browser_session_registry().close(conversation_id)
            await conv_repo.hard_delete(conversation_id)
        await session.execute(
            update(Board)
            .where(Board.user_id == user_id, Board.folder_id == folder_id)
            .values(folder_id=None)
        )
        await session.commit()

    # Server-side cloud root + snapshots (also clears any residual server mirror for
    # local projects). Never the user's OS directory behind ``local_root_id``.
    await purge_folder_space(user_id=user_id, folder_id=folder_id)

    async with async_session_factory() as session:
        await FolderRepository(session).hard_delete(folder_id)
    return True
