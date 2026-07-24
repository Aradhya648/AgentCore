"""EscalateTool logging — ``worker.escalate`` records「为什么升级」(question + assumption).

决策可观测回归：``worker.escalate`` used to carry only ``run_id`` / ``blocking`` / ``kind`` /
``has_assumption`` — i.e. that AN escalation happened and its type, but never its substance.
Now it also logs ``question`` (the待决问题原文, preview-capped) and ``assumption`` (the超时
回落), so an offline analysis of the product-AI logs can read WHY a worker escalated and where
it was blocked, straight from the line — no DB round-trip. These drive the non-blocking path
(no live escalation channel), which still emits the log before returning its CONTINUE ack.
"""

from pathlib import Path

import agentcore.tools.builtin.escalate as escalate_mod
from agentcore.tools.builtin.escalate import EscalateTool
from agentcore.tools.protocol import ToolContext
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
