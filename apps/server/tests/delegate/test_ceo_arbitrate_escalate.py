"""D1: coordination-active blocking escalate → CEO resolve_escalation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentcore.runtime.coordination.inject import format_coordination_events
from agentcore.runtime.coordination.session import (
    CoordinationEvent,
    CoordinationEventKind,
    CoordinationSession,
    clear_active_coordination,
    set_active_coordination,
)
from agentcore.runtime.coordination.tools import ResolveEscalationTool
from agentcore.runtime.interaction import InteractionKind, InteractionRegistry
from agentcore.tools.builtin.escalate import EscalateTool, escalate_tool_result
from agentcore.tools.protocol import EscalationChannel, EscalationOutcome, ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def _ctx(*, execution_id: str = "e-d1", escalation: EscalationChannel | None = None) -> ToolContext:
    return ToolContext(
        execution_id=execution_id,
        run_id="r1",
        agent_id="w1",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c1",
        agent_role="研究员",
        escalation=escalation,
    )


def test_escalate_tool_result_ceo_wording():
    resolved = escalate_tool_result("resolved", "用 Postgres", "暂按 MySQL", arbitrated_by="ceo")
    assert "主管就你的升级问题裁决" in resolved.output
    assert "用 Postgres" in resolved.output
    user = escalate_tool_result("resolved", "用 Postgres", "暂按 MySQL", arbitrated_by="user")
    assert "用户就你的升级问题答复" in user.output


def test_inject_blocking_escalation_prompts_resolve():
    session = CoordinationSession(execution_id="e", total_workers=2)
    text = format_coordination_events(
        session,
        [
            CoordinationEvent(
                kind=CoordinationEventKind.ESCALATION,
                payload={
                    "run_id": "r1",
                    "role": "研究员",
                    "kind": "normal",
                    "question": "选 Postgres 还是 MySQL？",
                    "assumption": "暂按 Postgres",
                    "blocking": True,
                    "source": "blocking_arbitrate",
                },
            )
        ],
    )
    assert "阻塞仲裁" in text
    assert "resolve_escalation" in text
    assert "via_user=true" in text
    assert "ask_user" in text


@pytest.mark.asyncio
async def test_blocking_escalate_routes_to_ceo_when_coordination_active():
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-d1", total_workers=2)
    set_active_coordination(session)
    seen: list[str] = []

    async def _request(q, a, questions, kind, awaiting="user"):
        seen.append(awaiting)
        assert awaiting == "ceo"
        return EscalationOutcome(status="resolved", answer="用 Postgres")

    channel = EscalationChannel(armed=True, request=_request)
    try:
        result = await EscalateTool().execute(
            {
                "question": "选库？",
                "assumption": "暂按 Postgres",
                "blocking": True,
            },
            _ctx(escalation=channel),
        )
        assert result.success is True
        assert "主管就你的升级问题裁决" in result.output
        assert seen == ["ceo"]
    finally:
        clear_active_coordination("e-d1")
        clear_active_coordination()


@pytest.mark.asyncio
async def test_blocking_escalate_stays_user_without_coordination():
    """Invariant B: no coordination session → awaiting=user (never ceo).

    Solo / classic blocking has no live CEO inside ``delegate``; hanging on CEO
    would deadlock. ``resolve_escalation`` is coordination-only.
    """
    clear_active_coordination()
    seen: list[str] = []

    async def _request(q, a, questions, kind, awaiting="user"):
        seen.append(awaiting)
        return EscalationOutcome(status="resolved", answer="用 Postgres")

    channel = EscalationChannel(armed=True, request=_request)
    result = await EscalateTool().execute(
        {
            "question": "选库？",
            "assumption": "暂按 Postgres",
            "blocking": True,
        },
        _ctx(execution_id="e-classic", escalation=channel),
    )
    assert result.success is True
    assert "用户就你的升级问题答复" in result.output
    assert seen == ["user"]


@pytest.mark.asyncio
async def test_resolve_escalation_settles_live_bridge():
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-d1", total_workers=2)
    set_active_coordination(session)
    registry = InteractionRegistry()
    fut = registry.create(
        "esc1",
        "c1",
        kind=InteractionKind.ESCALATION,
        payload={"awaiting": "ceo", "run_id": "r1"},
    )
    session.register_arbitration(
        "r1",
        escalation_id="esc1",
        conversation_id="c1",
        question="选库？",
        assumption="暂按 Postgres",
    )

    # Patch the tool to use our registry
    import agentcore.runtime.coordination.tools as tools_mod

    original = tools_mod.default_interaction_registry
    tools_mod.default_interaction_registry = lambda: registry
    try:
        result = await ResolveEscalationTool().execute(
            {"run_id": "r1", "answer": "用 Postgres", "via_user": False},
            _ctx(),
        )
        assert result.success is True
        assert fut.done()
        assert fut.result() == {"answer": "用 Postgres", "via_user": False}
        assert session.get_arbitration("r1") is None
    finally:
        tools_mod.default_interaction_registry = original
        clear_active_coordination("e-d1")
        clear_active_coordination()


@pytest.mark.asyncio
async def test_resolve_escalation_stashes_when_no_live_pending():
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-d1", total_workers=2)
    set_active_coordination(session)
    try:
        result = await ResolveEscalationTool().execute(
            {"run_id": "r1", "answer": "用 Postgres", "via_user": True},
            _ctx(),
        )
        assert result.success is True
        stashed = session.take_stashed_resolution("r1")
        assert stashed is not None
        assert stashed["answer"] == "用 Postgres"
        assert stashed["via_user"] is True
    finally:
        clear_active_coordination("e-d1")
        clear_active_coordination()


@pytest.mark.asyncio
async def test_resolve_escalation_soft_success_when_session_inactive():
    """会话已收口（团队全部完成）：resolve_escalation 幂等软化为 success 提示，不硬 error。

    对齐 UpdateSynthesisTool：``session is None``（从未开团）才硬 error；``not active``
    （已收口）给软成功，避免烧掉 CEO 一轮重试。
    """
    clear_active_coordination()
    session = CoordinationSession(execution_id="e-d1", total_workers=2)
    session.close()  # 团队完成、会话收口
    set_active_coordination(session)
    try:
        result = await ResolveEscalationTool().execute(
            {"run_id": "r1", "answer": "用 Postgres"},
            _ctx(),
        )
        assert result.success is True
        assert not result.error
        assert "收口" in result.output
    finally:
        clear_active_coordination("e-d1")
        clear_active_coordination()


@pytest.mark.asyncio
async def test_arbitration_snapshot_roundtrip():
    session = CoordinationSession(execution_id="e", total_workers=2)
    session.register_arbitration(
        "r1",
        escalation_id="esc1",
        conversation_id="c1",
        question="Q",
        assumption="A",
    )
    session.stash_resolution("r2", answer="ans", via_user=True, escalation_id="esc2")
    snap = session.snapshot()
    restored = CoordinationSession.from_snapshot(snap)
    assert restored.get_arbitration("r1")["escalation_id"] == "esc1"
    stashed = restored.take_stashed_resolution("r2")
    assert stashed["answer"] == "ans"
    assert stashed["via_user"] is True
