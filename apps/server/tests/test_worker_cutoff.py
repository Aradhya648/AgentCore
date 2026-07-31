"""Worker 掐断透明化 (C) + 收尾窗口 (B)：原因码、超时预警、预算软顶。"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from agentcore.llm.provider.protocol import TokenUsage
from agentcore.runtime.coordination.session import (
    CoordinationEventKind,
    CoordinationSession,
    clear_active_coordination,
    set_active_coordination,
)
from agentcore.runtime.delegate.completion import (
    collect_worker_gaps,
    format_worker_gaps_block,
)
from agentcore.runtime.delegate.delivery_status import build_delivery_status
from agentcore.runtime.engine.ceiling import ceiling_finalize
from agentcore.runtime.events import FinishReason
from agentcore.runtime.runs.cutoff import (
    DEGRADED_HANDOFF_WARNING,
    REASON_DEGRADED_HANDOFF,
    REASON_TOKEN_BUDGET,
    REASON_WORKER_TIMEOUT,
    TOKEN_BUDGET_WARNING,
    WIND_DOWN_ALLOWED_TOOLS,
    WORKER_TIMEOUT_WARNING,
    narrow_tools_for_wind_down,
    should_enter_token_wind_down,
)
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState


def test_collect_worker_gaps_emits_reason_codes():
    from agentcore.runtime.runs.file_acceptance import build_file_acceptance

    plan = RunPlan(
        nodes=[
            RunSpec(run_id="w1", task="调研", role="研究员"),
            RunSpec(run_id="w2", task="做PPT", role="设计师", depends_on=["w1"]),
        ]
    )
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="调研稿",
            warnings=[TOKEN_BUDGET_WARNING],
        ),
        "w2": RunState(
            phase=RunPhase.COMPLETED,
            content="脚本",
            files_touched=["build.py"],
            file_acceptance=build_file_acceptance(
                ["build.py"], phase=RunPhase.COMPLETED
            ),
            warnings=[WORKER_TIMEOUT_WARNING],
            debrief={"summary": "合成", "degraded": True},
        ),
    }
    gaps = collect_worker_gaps(plan, results)
    by_role = {role: rows for role, rows in gaps}
    assert by_role["研究员"][0]["reason"] == REASON_TOKEN_BUDGET
    reasons_w2 = {r.get("reason") for r in by_role["设计师"]}
    assert REASON_WORKER_TIMEOUT in reasons_w2
    assert REASON_DEGRADED_HANDOFF in reasons_w2

    payload = build_delivery_status(plan, results, execution_id="e-cut")
    assert payload is not None
    assert payload["state"] == "partial"
    coded = [g for g in payload["gaps"] if g.get("reason")]
    assert {g["reason"] for g in coded} >= {
        REASON_TOKEN_BUDGET,
        REASON_WORKER_TIMEOUT,
        REASON_DEGRADED_HANDOFF,
    }

    block = format_worker_gaps_block(gaps)
    assert "部分交付" in block
    assert "综述强制" not in block
    assert "完整" in block or "全部完成" in block
    assert "不必逐条复述" in block
    assert REASON_TOKEN_BUDGET in block
    assert DEGRADED_HANDOFF_WARNING in block


@pytest.mark.asyncio
async def test_ceiling_finalize_stamps_token_budget_on_track():
    """正轨撞顶：不标 DEGRADED，但 cutoff_reason_sink 写入 token_budget。"""
    cutoff: list[str] = []
    finish: list[FinishReason] = []
    controller = MagicMock()
    controller.is_thrashing.return_value = False

    class _ForceFinalize:
        async def __call__(self, **_kwargs):
            return "已有产出", "", TokenUsage(), 4, None

    with patch(
        "agentcore.runtime.engine.ceiling.force_finalize",
        new=_ForceFinalize(),
    ):
        await ceiling_finalize(
            messages=[],
            llm=MagicMock(),
            profile=MagicMock(max_rounds=28),
            active_model="m",
            base_model="m",
            tools=MagicMock(),
            allowed_tool_names=None,
            disabled_tools=set(),
            emit_content=lambda _d: None,
            emit_reasoning=lambda _d: None,
            emit_reset=lambda _r: None,
            final_content="已有产出",
            final_reasoning="",
            total_usage=TokenUsage(input_tokens=70_000, output_tokens=15_000),
            ceiling_reason="token_budget",
            round_idx=4,
            role="worker",
            run_id="del_w1",
            token_budget=80_000,
            controller=controller,
            tool_context=MagicMock(agent_id="a1"),
            sink=MagicMock(),
            finish_override_sink=finish,
            gate_escalation_sink=[],
            cutoff_reason_sink=cutoff,
        )
    assert cutoff == [REASON_TOKEN_BUDGET]
    assert finish == []  # 正轨不标 DEGRADED


async def _run_coordinated_worker(
    *,
    notified: bool,
    entered_wind_down: bool,
    debrief: dict | None,
) -> RunState:
    """Drive one worker through ``wrap_executor_with_timeouts``, simulating the
    post-arm session state (CEO TIMEOUT fired / wind-down consumed) from inside the
    fake executor — so the wrapper's stamp decision is exercised deterministically.
    """
    from agentcore.runtime.coordination.bridge import wrap_executor_with_timeouts

    clear_active_coordination()
    session = CoordinationSession(execution_id="exec-stamp", total_workers=1)
    spec = RunSpec(run_id="reviewer", task="学术审校", role="学术审校员")
    spec.policy.timeout_s = 60  # 计时器测试期内不会真正触发；disarm 会取消它

    async def fake_executor(s: RunSpec, _completed: dict) -> RunState:
        # arm 已在包装器内跑过（会重置这些集合）；此处模拟执行期内计时器/引擎的置位。
        if notified:
            session._timeout_notified.add(s.run_id)  # 模拟 CEO TIMEOUT 通知已发
        if entered_wind_down:
            session._timeout_wind_down_pending.add(s.run_id)
            assert session.consume_timeout_wind_down(s.run_id) is True
        return RunState(phase=RunPhase.COMPLETED, content="审校报告", debrief=debrief)

    wrapped = wrap_executor_with_timeouts(fake_executor, session)
    state = await wrapped(spec, {})
    await asyncio.sleep(0)  # 让 disarm 的取消传播，避免遗留计时任务告警
    clear_active_coordination()
    return state


@pytest.mark.asyncio
async def test_timeout_notified_natural_completion_not_stamped():
    """超时通知后自然完成（合格 handoff、未进 wind-down）→ 不盖 worker_timeout 章。

    复刻真实 trace 1fd37500b7ed49f09872650f2d8ffb16：审校员 120s 阈值、126s 自然完成并
    交付完整报告 —— 仅收到超时通知不再渲染成「交付可能缩水」假缺口。
    """
    state = await _run_coordinated_worker(
        notified=True,
        entered_wind_down=False,
        debrief={"summary": "完整审校报告 + 修改建议"},  # 合格交接（非 degraded）
    )
    assert WORKER_TIMEOUT_WARNING not in (state.warnings or [])


@pytest.mark.asyncio
async def test_timeout_notified_degraded_handoff_stamped():
    """超时通知 + degraded handoff（交接简报由引擎降级合成）→ 盖 worker_timeout 章。"""
    state = await _run_coordinated_worker(
        notified=True,
        entered_wind_down=False,
        debrief={"summary": "引擎降级合成", "degraded": True},
    )
    assert WORKER_TIMEOUT_WARNING in state.warnings


@pytest.mark.asyncio
async def test_timeout_notified_entered_wind_down_stamped():
    """超时通知 + 真正进入过 timeout wind-down（工具面被收窄）→ 盖 worker_timeout 章。"""
    state = await _run_coordinated_worker(
        notified=True,
        entered_wind_down=True,
        debrief={"summary": "已在收尾窗口内落盘交卷"},  # 合格交接，仅靠 wind-down 痕迹盖章
    )
    assert WORKER_TIMEOUT_WARNING in state.warnings


@pytest.mark.asyncio
async def test_wind_down_without_notification_not_stamped():
    """进过 wind-down 但硬顶通知未发（预警窗内完成）→ AND 门未过，不盖章。"""
    state = await _run_coordinated_worker(
        notified=False,
        entered_wind_down=True,
        debrief={"summary": "预警后一轮内交卷"},
    )
    assert WORKER_TIMEOUT_WARNING not in (state.warnings or [])


@pytest.mark.asyncio
async def test_timeout_warn_before_notify():
    """超时两段式：warn 先于 CEO TIMEOUT；consume 供收尾窗口；硬收尾后可 force-cancel。"""
    clear_active_coordination()
    session = CoordinationSession(execution_id="exec-warn", total_workers=1)
    set_active_coordination(session)
    with patch("agentcore.config.settings") as settings:
        settings.engine_worker_timeout_warn_ratio = 0.4
        session.arm_worker_timeout("w-slow", role="慢工", timeout_s=0.1)
        # 等到 warn 窗口（0.04s）之后、硬通知（0.1s）之前
        await asyncio.sleep(0.06)
        assert session.consume_timeout_wind_down("w-slow") is True
        assert session.consume_timeout_wind_down("w-slow") is False  # once
        assert not session.was_timeout_notified("w-slow")
        events = await session.wait_events(timeout=1.0)
        assert any(e.kind is CoordinationEventKind.TIMEOUT for e in events)
        assert session.was_timeout_notified("w-slow")
        # Hard TIMEOUT itself does not instantly cancel — grace round first.
        # Force-cancel is armed after grace (engine / grace_wall).
        assert "w-slow" not in session.cancel_run_ids()
    session.disarm_worker_timeout("w-slow")
    clear_active_coordination()


def test_token_wind_down_threshold_and_tool_narrowing():
    """收尾窗口：绝对留量阈值 + 工具收窄到落盘/handoff（剔除调查类）。"""
    # ceiling=80k, reserve=30k → soft at 50k
    assert should_enter_token_wind_down(50_000, 80_000, 30_000) is True
    assert should_enter_token_wind_down(49_999, 80_000, 30_000) is False
    assert should_enter_token_wind_down(80_000, 80_000, 0) is False  # reserve off
    assert should_enter_token_wind_down(10, 0, 30_000) is False  # budget off
    assert should_enter_token_wind_down(1, 30_000, 30_000) is False  # reserve >= ceiling
    assert should_enter_token_wind_down(1, 20_000, 30_000) is False  # reserve > ceiling

    # 收尾窗口本意「落盘 + handoff」，分段长文落盘要靠 file_append，白名单不可漏它。
    assert "file_append" in WIND_DOWN_ALLOWED_TOOLS
    available = {
        "web_search",
        "handoff",
        "file_write",
        "file_append",
        "file_list",
        "code_execute",
    }
    narrowed = narrow_tools_for_wind_down(
        available,
        allowed=["web_search", "handoff", "file_write", "file_append", "file_list"],
    )
    assert "handoff" in narrowed
    assert "file_write" in narrowed
    assert "file_append" in narrowed  # 追加写在收尾窗口可用（钉死）
    assert "web_search" not in narrowed
    assert "code_execute" not in narrowed
    assert set(narrowed) <= (WIND_DOWN_ALLOWED_TOOLS | {"handoff"})


def test_wind_down_keeps_file_read_for_files_deliverable():
    """交付类（工具面含 file_write）wind_down 保留 file_read；检索类不放回。"""
    from agentcore.runtime.runs.cutoff import (
        wind_down_allowed_tools,
        wind_down_breach_tool_names,
        worker_keeps_file_read_in_wind_down,
    )

    available = {
        "web_search",
        "read_url",
        "grep",
        "file_read",
        "file_write",
        "file_append",
        "handoff",
        "code_execute",
    }
    allowed = [
        "web_search",
        "read_url",
        "grep",
        "file_read",
        "file_write",
        "file_append",
        "handoff",
    ]
    assert worker_keeps_file_read_in_wind_down(available=available, allowed=allowed)
    narrowed = narrow_tools_for_wind_down(available, allowed=allowed)
    assert "file_read" in narrowed
    assert "file_write" in narrowed
    assert "handoff" in narrowed
    assert "web_search" not in narrowed
    assert "read_url" not in narrowed
    assert "grep" not in narrowed
    assert "code_execute" not in narrowed

    whitelist = wind_down_allowed_tools(keep_file_read=True)
    assert "file_read" in whitelist
    assert wind_down_breach_tool_names(["file_read", "handoff"], allowed=whitelist) == []
    assert wind_down_breach_tool_names(["web_search"], allowed=whitelist) == ["web_search"]

    # Prose worker（工具面无 file_write）不保留 file_read。
    prose_available = {"file_read", "web_search", "handoff", "ask_user"}
    prose_allowed = ["file_read", "web_search", "handoff", "ask_user"]
    assert not worker_keeps_file_read_in_wind_down(
        available=prose_available, allowed=prose_allowed
    )
    prose_narrowed = narrow_tools_for_wind_down(prose_available, allowed=prose_allowed)
    assert "file_read" not in prose_narrowed
    assert "handoff" in prose_narrowed
    assert "web_search" not in prose_narrowed


def test_wind_down_breach_detection_and_local_force():
    """非白名单工具 = 违约；二次违约或已过硬顶 → 本地收口，禁止再烧 token。"""
    from agentcore.runtime.runs.cutoff import (
        narrow_tools_for_handoff_only,
        should_force_local_after_wind_down_breach,
        wind_down_breach_tool_names,
    )

    assert wind_down_breach_tool_names(["handoff", "file_write"]) == []
    assert wind_down_breach_tool_names(["web_search", "handoff"]) == ["web_search"]
    assert wind_down_breach_tool_names(["web_search", "web_search", "read_url"]) == [
        "web_search",
        "read_url",
    ]

    assert narrow_tools_for_handoff_only({"handoff", "file_write"}) == ["handoff"]
    assert narrow_tools_for_handoff_only({"file_write"}) == []

    from agentcore.runtime.runs.cutoff import narrow_tools_for_wind_down_breach

    # Pending landing: breach keeps write tools (not handoff-only).
    landing_surface = narrow_tools_for_wind_down_breach(
        {"handoff", "file_write", "file_append", "web_search"},
        keep_landing=True,
        keep_file_read=False,
    )
    assert "file_write" in landing_surface
    assert "file_append" in landing_surface
    assert "handoff" in landing_surface
    assert "web_search" not in landing_surface

    # No landing obligation: breach collapses to handoff-only.
    assert narrow_tools_for_wind_down_breach(
        {"handoff", "file_write", "web_search"},
        keep_landing=False,
    ) == ["handoff"]

    # First breach under ceiling → nudge path (not local).
    assert (
        should_force_local_after_wind_down_breach(
            prior_breaches=0, tokens=100_000, token_budget=120_000
        )
        is False
    )
    # Retrieval-budget wind-down: first breach already forces local (avoid thrash).
    assert (
        should_force_local_after_wind_down_breach(
            prior_breaches=0,
            tokens=100_000,
            token_budget=120_000,
            wind_down_reason="retrieval_budget",
        )
        is True
    )
    # First breach already at/over hard ceiling → local (违约轮不得再烧过硬顶).
    assert (
        should_force_local_after_wind_down_breach(
            prior_breaches=0, tokens=120_000, token_budget=120_000
        )
        is True
    )
    # Second breach always local.
    assert (
        should_force_local_after_wind_down_breach(
            prior_breaches=1, tokens=50_000, token_budget=120_000
        )
        is True
    )


@pytest.mark.asyncio
async def test_wind_down_breach_journals_denied_tool(monkeypatch):
    """wind_down 拒执行须落 durable tool_use_end，journal 可查。"""
    from pathlib import Path

    from agentcore.config import settings
    from agentcore.core.types import ToolCategory
    from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, ToolCallDelta
    from agentcore.runtime.engine import react_loop
    from agentcore.runtime.events import EventSink
    from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
    from agentcore.tools.registry import ToolRegistry
    from agentcore.tools.sandbox.subprocess import SubprocessSandbox
    from agentcore.workspace.server import ServerWorkspace
    from tests.llm_helpers import make_profile_params

    monkeypatch.setattr(settings, "engine_worker_token_wind_down_reserve", 30_000)

    class _Scripted:
        def __init__(self) -> None:
            self.calls = 0

        async def stream(self, request):  # noqa: ANN001
            c = self.calls
            self.calls += 1
            if c == 0:
                # Jump past soft reserve into wind_down via a search call.
                yield LLMChunk(
                    delta_tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="c0",
                            function_name="web_search",
                            arguments_delta='{"query":"x"}',
                        )
                    ]
                )
                yield LLMChunk(
                    usage=TokenUsage(input_tokens=50_000, output_tokens=40_000)
                )
                return
            if c == 1:
                # Already in wind_down — breach with web_search (denied + journaled).
                yield LLMChunk(
                    delta_tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="c1",
                            function_name="web_search",
                            arguments_delta='{"query":"y"}',
                        )
                    ]
                )
                yield LLMChunk(usage=TokenUsage(input_tokens=100, output_tokens=50))
                return
            yield LLMChunk(delta_content="handoff done")
            yield LLMChunk(usage=TokenUsage(input_tokens=50, output_tokens=20))

    class _Stub:
        def __init__(self, name: str, *, category: ToolCategory) -> None:
            self._name = name
            self._category = category

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name=self._name,
                description="stub",
                parameters={"type": "object", "properties": {}},
                category=self._category,
            )

        async def execute(self, arguments, context) -> ToolResult:  # noqa: ANN001
            return ToolResult(tool_call_id="", success=True, output="ok")

    reg = ToolRegistry()
    for name, cat in (
        ("web_search", ToolCategory.SEARCH),
        ("file_write", ToolCategory.FILESYSTEM),
        ("handoff", ToolCategory.ORCHESTRATION),
    ):
        reg.register(_Stub(name, category=cat))

    sink = EventSink()
    messages: list[LLMMessage] = [LLMMessage(role="user", content="go")]
    await react_loop(
        messages=messages,
        llm=_Scripted(),
        tools=reg,
        sink=sink,
        tool_context=ToolContext(
            execution_id="e",
            run_id="w1",
            agent_id="a",
            backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
            user_id="u",
        ),
        profile=make_profile_params(max_rounds=8),
        turn_model="m",
        role="worker",
        run_id="w1",
        token_budget=80_000,
        allowed_tool_names=["web_search", "file_write", "handoff"],
    )

    journal = list(sink._journal)
    ends = [
        e
        for e in journal
        if e.get("type") == "tool_use_end"
        and (e.get("payload") or {}).get("tool_name") == "web_search"
        and (e.get("payload") or {}).get("status") == "error"
    ]
    assert ends, f"expected journaled wind_down deny for web_search, got {journal!r}"
    assert any("收尾窗口" in ((e.get("payload") or {}).get("result") or "") for e in ends)


@pytest.mark.asyncio
async def test_single_round_jump_past_soft_still_gets_wind_down(monkeypatch):
    """单轮 token 从软顶下直冲硬顶上：必有一轮收尾窗，不直撞禁写 finalize。"""
    from pathlib import Path

    from agentcore.config import settings
    from agentcore.core.types import ToolCategory
    from agentcore.llm.provider.protocol import LLMChunk, LLMMessage, ToolCallDelta
    from agentcore.runtime.engine import react_loop
    from agentcore.runtime.events import EventSink
    from agentcore.runtime.runs.cutoff import WIND_DOWN_INSTRUCTION_TOKEN
    from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
    from agentcore.tools.registry import ToolRegistry
    from agentcore.tools.sandbox.subprocess import SubprocessSandbox
    from agentcore.workspace.server import ServerWorkspace
    from tests.llm_helpers import make_profile_params

    monkeypatch.setattr(settings, "engine_worker_token_wind_down_reserve", 30_000)

    class _Scripted:
        def __init__(self) -> None:
            self.calls = 0
            self.round_tool_names: list[list[str]] = []

        async def stream(self, request):  # noqa: ANN001
            self.round_tool_names.append(
                [t["function"]["name"] for t in (request.tools or [])]
            )
            c = self.calls
            self.calls += 1
            if c == 0:
                # One round jumps 0 → 90k (past soft 50k and hard 80k).
                yield LLMChunk(
                    delta_tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="c0",
                            function_name="web_search",
                            arguments_delta="{}",
                        )
                    ]
                )
                yield LLMChunk(
                    usage=TokenUsage(input_tokens=50_000, output_tokens=40_000)
                )
                return
            # Wind-down round: land and stop (no further tools).
            yield LLMChunk(delta_content="已落盘交卷")
            yield LLMChunk(usage=TokenUsage(input_tokens=100, output_tokens=50))

    class _Stub:
        def __init__(self, name: str, *, category: ToolCategory) -> None:
            self._name = name
            self._category = category

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name=self._name,
                description="stub",
                parameters={"type": "object", "properties": {}},
                category=self._category,
            )

        async def execute(self, arguments, context) -> ToolResult:  # noqa: ANN001
            return ToolResult(tool_call_id="", success=True, output="ok")

    reg = ToolRegistry()
    for name, cat in (
        ("web_search", ToolCategory.SEARCH),
        ("file_write", ToolCategory.FILESYSTEM),
        ("handoff", ToolCategory.ORCHESTRATION),
    ):
        reg.register(_Stub(name, category=cat))

    provider = _Scripted()
    messages: list[LLMMessage] = [LLMMessage(role="user", content="go")]
    content, _r, usage, _rounds = await react_loop(
        messages=messages,
        llm=provider,
        tools=reg,
        sink=EventSink(),
        tool_context=ToolContext(
            execution_id="e",
            run_id="w1",
            agent_id="a",
            backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
            user_id="u",
        ),
        profile=make_profile_params(max_rounds=8),
        turn_model="m",
        role="worker",
        run_id="w1",
        token_budget=80_000,
        allowed_tool_names=["web_search", "file_write", "handoff"],
    )

    assert usage.total_tokens >= 80_000
    assert any(
        (m.content or "").startswith(WIND_DOWN_INSTRUCTION_TOKEN[:12])
        or "收尾窗口" in (m.content or "")
        for m in messages
    )
    # Second LLM call is the wind-down round (not a ban-write finalize).
    assert len(provider.round_tool_names) >= 2
    wind_tools = set(provider.round_tool_names[1])
    assert "file_write" in wind_tools
    assert "handoff" in wind_tools
    assert "web_search" not in wind_tools
    assert "已落盘" in content or content.strip()
