"""followups DERIVED 持久化 round-trip (下一步推荐).

The post-turn「下一步推荐」chips are the twin of the conversation title: minted by the
same finalize tail and written back onto the assistant row so reopening a conversation
replays them. These pin the durable half — ``set_followups`` writes, and the read path
(``get_by_id`` + ``MessageDetail`` projection) returns them. Real PostgreSQL; auto-skips
without it (see ``integration/conftest``).
"""

from __future__ import annotations

from agentcore.api.schemas.messages import MessageDetail
from agentcore.db.repositories import (
    ConversationRepository,
    MessageRepository,
    UserRepository,
)


async def test_followups_persist_and_project(session_factory) -> None:
    """set_followups makes the chips survive a reload; a fresh row starts empty."""
    async with session_factory() as s:
        user = await UserRepository(s).create(username="fu-user", display_name="U")
        conv = await ConversationRepository(s).create(user_id=user.user_id, title="chat")

    async with session_factory() as s:
        msg = await MessageRepository(s).create(
            conversation_id=conv.id, role="assistant", content="好的，方案如下"
        )

    # A just-created assistant row has no chips yet (server_default '[]').
    async with session_factory() as s:
        row = await MessageRepository(s).get_by_id(msg.id, conversation_id=conv.id)
        assert row is not None
        assert row.followups == []
        assert MessageDetail.model_validate(row).followups == []

    # The finalize tail writes the minted chips onto THIS row.
    chips = ["帮我导出 PDF", "再做一版竞品对比"]
    async with session_factory() as s:
        await MessageRepository(s).set_followups(
            msg.id, conversation_id=conv.id, followups=chips
        )

    # Reload sees them — durable on the row and through the read projection.
    async with session_factory() as s:
        row = await MessageRepository(s).get_by_id(msg.id, conversation_id=conv.id)
        assert row is not None
        assert row.followups == chips
        assert MessageDetail.model_validate(row).followups == chips


async def test_set_followups_is_conversation_scoped(session_factory) -> None:
    """A mismatched conversation_id is a harmless no-op (defense in depth)."""
    async with session_factory() as s:
        user = await UserRepository(s).create(username="fu-user2", display_name="U2")
        conv = await ConversationRepository(s).create(user_id=user.user_id, title="chat")

    async with session_factory() as s:
        msg = await MessageRepository(s).create(
            conversation_id=conv.id, role="assistant", content="hi"
        )

    async with session_factory() as s:
        await MessageRepository(s).set_followups(
            msg.id,
            conversation_id="00000000-0000-0000-0000-000000000000",
            followups=["不该落到别的会话"],
        )

    async with session_factory() as s:
        row = await MessageRepository(s).get_by_id(msg.id, conversation_id=conv.id)
        assert row is not None
        assert row.followups == []
