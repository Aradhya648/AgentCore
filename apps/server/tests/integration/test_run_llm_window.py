"""Diagnostic LLM window REST — owner-scoped fold from turn_journal."""

from uuid import uuid4

import pytest

from agentcore.db.repositories import (
    ConversationRepository,
    MessageRepository,
    TurnJournalRepository,
    UserRepository,
)
from agentcore.runtime.facts import (
    LlmCallFact,
    RoundBoundaryFact,
    ToolCallFact,
    TurnStartedFact,
)
from tests.integration.conftest import register_and_login


async def _resolve_user_and_conversation(session_factory, username: str, title: str):
    async with session_factory() as session:
        user = await UserRepository(session).get_by_username(username)
        assert user is not None
        conv = await ConversationRepository(session).create(user_id=user.user_id, title=title)
        return user.user_id, conv.id


async def _seed_turn_with_journal(
    session_factory,
    *,
    conversation_id: str,
    turn_id: str,
    run_id: str = "cap",
):
    entries = [
        TurnStartedFact(
            system_prompt="你是 CEO。",
            user_message="调研一下",
            model_profile="chat",
            history_len=0,
        )
        .to_fact()
        .entry(),
        RoundBoundaryFact(round_idx=0, run_id=run_id, role="captain").to_fact().entry(),
        LlmCallFact(
            run_id=run_id,
            round_idx=0,
            reasoning_content="先搜索",
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "search", "arguments": '{"q":"x"}'},
                }
            ],
            finish_reason="tool_calls",
        )
        .to_fact()
        .entry(),
        ToolCallFact(
            run_id=run_id,
            tool_call_id="c1",
            name="search",
            arguments='{"q":"x"}',
            result="搜索结果",
            success=True,
        )
        .to_fact()
        .entry(),
    ]
    async with session_factory() as session:
        msg_repo = MessageRepository(session)
        await msg_repo.create(conversation_id=conversation_id, role="user", content="调研一下")
        await msg_repo.create(
            conversation_id=conversation_id,
            role="assistant",
            content="",
            message_id=turn_id,
        )
        await TurnJournalRepository(session).record(
            turn_id=turn_id,
            conversation_id=conversation_id,
            trace_id="trace-llm-window",
            entries=entries,
        )


@pytest.mark.asyncio
async def test_run_llm_window_owner_fold(client, session_factory, make_invite):
    turn_id = str(uuid4())
    run_id = "cap"
    username = f"llmwin_{uuid4().hex[:8]}"
    invite_code = await make_invite(f"INV-LLMWIN-{uuid4().hex[:6]}")
    await register_and_login(client, invite_code, username)
    _, conversation_id = await _resolve_user_and_conversation(
        session_factory, username, "llm window"
    )
    await _seed_turn_with_journal(
        session_factory,
        conversation_id=conversation_id,
        turn_id=turn_id,
        run_id=run_id,
    )

    r = await client.get(
        f"/v1/conversations/{conversation_id}/messages/{turn_id}/runs/{run_id}/llm-window"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["run_id"] == run_id
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert body["messages"][0]["content"] == "你是 CEO。"
    assert body["messages"][1]["content"] == "调研一下"
    assert body["messages"][2]["reasoning_content"] == "先搜索"
    assert body["messages"][2]["tool_calls"][0]["function"]["name"] == "search"
    assert body["messages"][3]["content"] == "搜索结果"


@pytest.mark.asyncio
async def test_run_llm_window_idor(client, session_factory, make_invite):
    turn_id = str(uuid4())
    owner_invite = await make_invite(f"INV-LLMW-OWN-{uuid4().hex[:6]}")
    attacker_invite = await make_invite(f"INV-LLMW-ATK-{uuid4().hex[:6]}")
    owner_name = f"llmwin_owner_{uuid4().hex[:8]}"
    attacker_name = f"llmwin_atk_{uuid4().hex[:8]}"
    await register_and_login(client, owner_invite, owner_name)
    _, conversation_id = await _resolve_user_and_conversation(
        session_factory, owner_name, "private"
    )
    await _seed_turn_with_journal(
        session_factory,
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    import httpx
    from httpx import ASGITransport

    from agentcore.main import app

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await register_and_login(other, attacker_invite, attacker_name)
        r = await other.get(
            f"/v1/conversations/{conversation_id}/messages/{turn_id}/runs/cap/llm-window"
        )
        assert r.status_code == 404
