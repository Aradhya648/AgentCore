"""辩论观测：主持人 attribution 透传 + 后续轮 gather 埋点口径。"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from agentcore.billing.attribution import (
    attribution_headers_from_context,
    parse_attribution_headers,
)
from agentcore.llm.credentials import (
    INFERENCE_CALL_HEADER,
    INFERENCE_RUN_HEADER,
)
from agentcore.llm.provider.protocol import LLMResponse, TokenUsage
from agentcore.runtime.debate import (
    DebateConfig,
    DebateForm,
    DebateSide,
    JudgeVerdict,
    Moderator,
    RoundPolicy,
    RoundResult,
    SideTurn,
)
from agentcore.runtime.debate import rounds as rounds_mod
from agentcore.runtime.debate.rounds import _log_gather_batch, next_round
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState
from tests.conftest import LogSpy


class _CaptureAttributionLLM:
    """Record attribution headers visible during each unary complete()."""

    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []
        self.scenarios: list[str] = []

    async def complete(self, request):  # noqa: ANN001
        self.scenarios.append(request.scenario)
        self.headers.append(attribution_headers_from_context())
        return LLMResponse(
            content=json.dumps({"focus": "成本"}),
            usage=TokenUsage(input_tokens=3, output_tokens=1),
        )


def test_moderator_complete_json_binds_run_attribution():
    """主持人 unary 调用必须把 run_id / persona 绑进 log context → attribution 头。"""
    llm = _CaptureAttributionLLM()
    mod = Moderator(
        provider=llm,
        model="m",
        run_id="debate_mod1",
        parent_run_id="ceo_run",
    )
    data = asyncio.run(mod._complete_json("sys", "user", "frame"))
    assert data == {"focus": "成本"}
    assert llm.scenarios == ["debate.frame"]
    assert len(llm.headers) == 1
    parsed = parse_attribution_headers(llm.headers[0])
    assert parsed["run_id"] == "debate_mod1"
    assert parsed["agent_id"] == "debate_mod1"
    assert parsed["parent_run_id"] == "ceo_run"
    assert parsed["role"] == "member"
    assert parsed["persona"] == "主持人"
    assert mod.usage.input_tokens == 3
    assert mod.llm_rounds == 1


def test_moderator_without_run_id_skips_run_attribution():
    """未注入 run_id 时不造假 run 头（单测假 provider / 旧调用面兼容）。"""
    llm = _CaptureAttributionLLM()
    mod = Moderator(provider=llm, model="m")
    asyncio.run(mod._complete_json("sys", "user", "assess"))
    assert llm.scenarios == ["debate.assess"]
    h = llm.headers[0]
    assert INFERENCE_RUN_HEADER not in h
    # attribution_headers_from_context always mints call_id even with empty context.
    assert INFERENCE_CALL_HEADER in h and h[INFERENCE_CALL_HEADER]


def test_log_gather_batch_mirrors_round1_fields(monkeypatch):
    """后续轮埋点字段名与 debate.round1.completed 对齐。"""
    spy = LogSpy()
    monkeypatch.setattr(rounds_mod, "logger", spy)
    _log_gather_batch(
        "debate.round2.completed",
        round_no=2,
        nodes=2,
        max_parallel=4,
        wall_ms=100,
        busy_ms=180,
        completed=2,
        failed=0,
    )
    kw = spy.get("debate.round2.completed")
    assert kw == {
        "nodes": 2,
        "width": 2,
        "peak": 2,
        "wall_ms": 100,
        "busy_ms": 180,
        "avg_parallelism": 1.8,
        "slot_starved": False,
        "completed": 2,
        "failed": 0,
        "skipped": 0,
        "round_no": 2,
    }


@pytest.mark.asyncio
async def test_next_round_emits_completed_log(monkeypatch):
    """next_round gather 收齐后发出 debate.roundN.completed。"""
    spy = LogSpy()
    monkeypatch.setattr(rounds_mod, "logger", spy)

    side = DebateSide(key="pro", name="正方", stance="支持")
    session = MagicMock()
    session.spec = RunSpec(run_id="r1_pro", agent_id="r1_pro", task="t", role="正方")
    session.transcript = []
    session.content = "旧"
    session.recall_count = 0

    tool = MagicMock()
    tool._debater_sessions = {"pro": session}
    tool._approval_gate = None
    tool._max_parallel = 2
    tool._base_tool_context.backend.location = "cloud"
    tool._llm = object()
    tool._tools = object()
    tool._sink = object()
    tool._profile_set = object()
    tool._acc = MagicMock()

    async def _fake_continue_run(**_kwargs):  # noqa: ANN003
        await asyncio.sleep(0.01)
        return RunState(phase=RunPhase.COMPLETED, content="新论点", transcript=[])

    import agentcore.runtime.runs as runs_mod

    monkeypatch.setattr(runs_mod, "continue_run", _fake_continue_run)

    config = DebateConfig(
        motion="X?",
        form=DebateForm.DEBATE,
        sides=[side],
        policy=RoundPolicy(thorough=False, max_rounds=3),
    )
    history = [
        RoundResult(
            round_no=1,
            focus="焦点",
            turns=[SideTurn("pro", "正方", "r1_pro", "上轮", ok=True)],
            verdict=JudgeVerdict(real_clash=True, new_arguments=True, converged=False),
            summary="小结",
        )
    ]

    turns = await next_round(
        tool,
        "exec",
        "debate_mod",
        config,
        2,
        "焦点2",
        [side],
        history,
    )
    assert len(turns) == 1 and turns[0].ok
    kw = spy.get("debate.round2.completed")
    assert kw["round_no"] == 2
    assert kw["nodes"] == 1
    assert kw["completed"] == 1
    assert kw["failed"] == 0
    assert kw["wall_ms"] >= 0
    assert kw["busy_ms"] >= 0
    assert "avg_parallelism" in kw
    assert "slot_starved" in kw
