"""EscalateTool logging — ``worker.escalate`` records「为什么升级」(question + assumption).

决策可观测回归：``worker.escalate`` used to carry only ``run_id`` / ``blocking`` / ``kind`` /
``has_assumption`` — i.e. that AN escalation happened and its type, but never its substance.
Now it also logs ``question`` (the待决问题原文, preview-capped) and ``assumption`` (the超时
回落), so an offline analysis of the product-AI logs can read WHY a worker escalated and where
it was blocked, straight from the line — no DB round-trip. These drive the non-blocking path
(no live escalation channel), which still emits the log before returning its CONTINUE ack.
"""

from pathlib import Path

import pytest

import agentcore.tools.builtin.escalate as escalate_mod
from agentcore.runtime.events.interaction import escalation_required
from agentcore.tools.builtin.escalate import EscalateTool
from agentcore.tools.protocol import EscalationChannel, EscalationOutcome, ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.conftest import LogSpy


def _ctx() -> ToolContext:
    # No escalation channel / on_escalate callback → the non-blocking escalate path, which
    # still emits worker.escalate before returning the "proceed on your assumption" ack.
    return ToolContext(
        execution_id="e",
        run_id="w1",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


async def test_worker_escalate_logs_question_and_assumption(monkeypatch):
    spy = LogSpy()
    monkeypatch.setattr(escalate_mod, "logger", spy)

    result = await EscalateTool().execute(
        {"question": "该走方案A还是方案B?", "assumption": "暂按方案A继续", "kind": "scope"},
        _ctx(),
    )

    assert result.success is True  # non-blocking escalate never stops the worker
    esc = spy.get("worker.escalate")
    assert esc["run_id"] == "w1"
    assert esc["kind"] == "scope"
    assert esc["blocking"] is False
    assert esc["has_assumption"] is True
    # the WHY + the fallback — the substance the enrichment adds
    assert esc["question"] == "该走方案A还是方案B?"
    assert esc["assumption"] == "暂按方案A继续"
    assert esc["browser_login"] is False


async def test_worker_escalate_question_preview_is_capped(monkeypatch):
    # A long question is clipped to a bounded preview (铁律: never the full 正文); no
    # assumption given → the assumption preview is empty (blocking defaults false, so an
    # assumption is not required).
    spy = LogSpy()
    monkeypatch.setattr(escalate_mod, "logger", spy)

    await EscalateTool().execute({"question": "为" * 500}, _ctx())

    esc = spy.get("worker.escalate")
    assert esc["question"].endswith("…")
    assert len(esc["question"]) == 201  # 200-char cap + the one ellipsis char
    assert esc["has_assumption"] is False
    assert esc["assumption"] == ""
    assert esc["browser_login"] is False


async def test_browser_login_promotes_to_blocking_and_requires_assumption(monkeypatch):
    """browser_login=true forces blocking; missing assumption is rejected."""
    spy = LogSpy()
    monkeypatch.setattr(escalate_mod, "logger", spy)

    result = await EscalateTool().execute(
        {"question": "请接管登录", "browser_login": True},
        _ctx(),
    )
    assert result.success is False
    assert "assumption" in (result.error or "")
    assert not any(name == "worker.escalate" for name, _ in spy.events)


async def test_browser_login_with_assumption_logs_promoted_blocking(monkeypatch):
    spy = LogSpy()
    monkeypatch.setattr(escalate_mod, "logger", spy)

    result = await EscalateTool().execute(
        {
            "question": "请接管登录",
            "assumption": "用户登录后继续",
            "browser_login": True,
            # blocking omitted — should promote
        },
        _ctx(),
    )
    assert result.success is True  # unarmed channel → non-blocking fallthrough after promote
    esc = spy.get("worker.escalate")
    assert esc["blocking"] is True
    assert esc["browser_login"] is True


def test_escalation_required_emits_browser_login_only_when_true():
    with_flag = escalation_required(
        "r1",
        "a1",
        escalation_id="e1",
        question="请登录",
        assumption="登录后继续",
        browser_login=True,
    )
    assert with_flag.payload.get("browser_login") is True

    without = escalation_required(
        "r1",
        "a1",
        escalation_id="e1",
        question="普通问题",
        assumption="暂按 A",
        browser_login=False,
    )
    assert "browser_login" not in without.payload

    omitted = escalation_required(
        "r1",
        "a1",
        escalation_id="e1",
        question="普通问题",
        assumption="暂按 A",
    )
    assert "browser_login" not in omitted.payload


@pytest.mark.asyncio
async def test_blocking_channel_forwards_browser_login():
    seen: dict = {}

    async def _request(
        q,
        a,
        questions,
        kind,
        awaiting="user",
        *,
        browser_login=False,
        ownership_paths=None,
        lock_owner_run_id="",
    ):
        seen["browser_login"] = browser_login
        seen["awaiting"] = awaiting
        return EscalationOutcome(status="resolved", answer="已登录")

    ctx = ToolContext(
        execution_id="e",
        run_id="w1",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c1",
        escalation=EscalationChannel(armed=True, request=_request),
    )
    result = await EscalateTool().execute(
        {
            "question": "请接管登录",
            "assumption": "用户登录后继续",
            "blocking": True,
            "browser_login": True,
        },
        ctx,
    )
    assert result.success is True
    assert seen["browser_login"] is True
    assert seen["awaiting"] == "user"
    assert "用户就你的升级问题答复" in result.output


@pytest.mark.asyncio
async def test_browser_login_skips_ceo_arbitration_when_coordination_active(monkeypatch):
    """Password login must stay user-facing even with a living CEO (never CEO-await)."""
    seen: dict = {}

    async def _request(
        q,
        a,
        questions,
        kind,
        awaiting="user",
        *,
        browser_login=False,
        ownership_paths=None,
        lock_owner_run_id="",
    ):
        seen["awaiting"] = awaiting
        seen["browser_login"] = browser_login
        return EscalationOutcome(status="resolved", answer="已登录")

    class _FakeCoord:
        active = True

    monkeypatch.setattr(
        "agentcore.runtime.coordination.session.active_coordination",
        lambda _eid: _FakeCoord(),
    )
    ctx = ToolContext(
        execution_id="e",
        run_id="w1",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
        conversation_id="c1",
        escalation=EscalationChannel(armed=True, request=_request),
    )
    result = await EscalateTool().execute(
        {
            "question": "请接管登录",
            "assumption": "用户登录后继续",
            "browser_login": True,
        },
        ctx,
    )
    assert result.success is True
    assert seen["browser_login"] is True
    assert seen["awaiting"] == "user"
