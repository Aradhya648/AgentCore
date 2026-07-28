"""跨回合同图追加：复用 execution_id、journal divert、收口不绑 message_end。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agentcore.runtime.delegate.graph_append import (
    GraphAppendRedirect,
    bind_redirect,
    clear_graph_host_registry,
    is_graph_growth_event,
    peek_graph_host,
    register_graph_host,
    reset_redirect,
)
from agentcore.runtime.events import EventSink, EventType, graph_append, run_plan
from agentcore.runtime.facts import Fact, record_turn_fact
from agentcore.runtime.journal.writer import TurnJournalWriter, current_journal_writer
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState
from agentcore.tools.protocol import ToolResult
from tests.delegate.conftest import Provider, ctx, tool


@pytest.fixture(autouse=True)
def _clean_graph_host_registry():
    clear_graph_host_registry()
    yield
    clear_graph_host_registry()


def test_register_graph_host_first_wins():
    register_graph_host("exec-a", "m1")
    register_graph_host("exec-a", "m2")
    assert peek_graph_host("exec-a") == "m1"


def test_is_graph_growth_event_matrix():
    assert is_graph_growth_event(EventType.RUN_PLAN, {"execution_id": "e"})
    assert is_graph_growth_event(EventType.RUN_STARTED, {"run_id": "r1"})
    assert not is_graph_growth_event(EventType.GRAPH_APPEND, {"execution_id": "e"})
    assert not is_graph_growth_event(EventType.TOOL_USE_START, {"tool_name": "delegate"})
    assert is_graph_growth_event(
        EventType.TOOL_USE_START, {"tool_name": "web_search", "run_id": "r1"}
    )


def test_sink_registers_host_and_graph_append_marker():
    sink = EventSink(message_id="m1", conversation_id="c")
    sink.emit(
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="t",
            agents=[
                {
                    "id": "w1",
                    "role": "研",
                    "thinking": True,
                }
            ],
            runs=[{"id": "r1", "agent_id": "w1", "task": "x", "depends_on": []}],
        )
    )
    assert peek_graph_host("exec1") == "m1"
    process = sink.process_timeline() or []
    assert any(s.get("kind") == "team" and s.get("execution_id") == "exec1" for s in process)

    sink2 = EventSink(message_id="m2", conversation_id="c")
    sink2.emit(
        graph_append(
            execution_id="exec1",
            host_message_id="m1",
            append_message_id="m2",
            added_count=1,
            roles=["写"],
            added_run_ids=["r2"],
        )
    )
    sink2.emit(
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="t2",
            agents=[
                {
                    "id": "w1",
                    "role": "研",
                    "thinking": True,
                },
                {
                    "id": "w2",
                    "role": "写",
                    "thinking": True,
                },
            ],
            runs=[
                {"id": "r1", "agent_id": "w1", "task": "x", "depends_on": []},
                {"id": "r2", "agent_id": "w2", "task": "y", "depends_on": []},
            ],
            host_message_id="m1",
        )
    )
    process2 = list(sink2._process)
    assert any(s.get("kind") == "graph_append" and s.get("added_count") == 1 for s in process2)
    assert not any(s.get("kind") == "team" for s in process2)


@pytest.mark.asyncio
async def test_journal_divert_to_host_writer():
    """生长 DURABLE 进宿主 writer；graph_append 留在当前 turn writer。"""
    host_entries: list[dict[str, Any]] = []
    cur_entries: list[dict[str, Any]] = []

    class _CaptureWriter(TurnJournalWriter):
        def __init__(self, bucket: list[dict[str, Any]], *, turn_id: str) -> None:
            super().__init__(
                turn_id=turn_id, conversation_id="c", trace_id=None, initial_seq=0
            )
            self._bucket = bucket

        def schedule_append(self, entry: dict[str, Any]):  # type: ignore[override]
            self._bucket.append(dict(entry))
            fut: asyncio.Future[int | None] = asyncio.get_running_loop().create_future()
            fut.set_result(len(self._bucket))
            return fut

    host_w = _CaptureWriter(host_entries, turn_id="m1")
    cur_w = _CaptureWriter(cur_entries, turn_id="m2")
    tok_j = current_journal_writer.set(cur_w)
    redir = GraphAppendRedirect(
        execution_id="exec1",
        host_message_id="m1",
        append_message_id="m2",
        host_writer=host_w,
    )
    tok_r = bind_redirect(redir)
    try:
        sink = EventSink(message_id="m2", conversation_id="c")
        sink.emit(
            graph_append(
                execution_id="exec1",
                host_message_id="m1",
                append_message_id="m2",
                added_count=1,
            )
        )
        sink.emit(
            run_plan(
                execution_id="exec1",
                plan_type="multi_agent",
                task_summary="t",
                agents=[],
                runs=[{"id": "r9", "agent_id": "w9", "task": "z", "depends_on": []}],
                host_message_id="m1",
            )
        )
        record_turn_fact(Fact(kind="plan_snapshot", payload={"nodes": []}))
    finally:
        reset_redirect(tok_r)
        current_journal_writer.reset(tok_j)

    assert any(e.get("kind") == "graph_append" for e in cur_entries)
    assert any(e.get("kind") == "run_plan" for e in host_entries)
    assert any(e.get("kind") == "plan_snapshot" for e in host_entries)
    assert not any(e.get("kind") == "run_plan" for e in cur_entries)


@pytest.mark.asyncio
async def test_delegate_append_reuses_execution_id(monkeypatch):
    """append_to_execution_id → drive 使用宿主 execution_id，不铸新 id。"""
    register_graph_host("exec-host", "m-host")

    host_plan = RunPlan(
        nodes=[
            RunSpec(run_id="r_old", agent_id="w_old", role="研究员", task="旧任务"),
        ]
    )
    seed = {"r_old": RunState(phase=RunPhase.COMPLETED, content="done")}

    async def fake_resolve(*, conversation_id: str, execution_id: str) -> str | None:
        assert execution_id == "exec-host"
        return "m-host"

    async def fake_load(host_message_id: str):
        assert host_message_id == "m-host"
        return host_plan, seed

    async def fake_open_writer(**kwargs):  # noqa: ANN003
        return TurnJournalWriter(
            turn_id="m-host", conversation_id="c", trace_id=None, initial_seq=10
        )

    captured: dict[str, Any] = {}

    async def fake_drive(tool, plan, **kwargs):  # noqa: ANN001
        captured["execution_id"] = kwargs.get("execution_id")
        captured["seed"] = kwargs.get("seed_completed")
        captured["node_ids"] = [n.run_id for n in plan.nodes]
        return ToolResult(tool_call_id="", success=True, output="ok")

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_host_message_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.load_host_plan_and_completed",
        fake_load,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.open_host_journal_writer",
        fake_open_writer,
    )
    monkeypatch.setattr("agentcore.tools.builtin.delegate.tool.drive", fake_drive)

    t = tool(Provider(["X"]))
    t._message_id = "m-new"
    t._conversation_id = "c"
    t._base_tool_context.execution_id = "exec-fresh"

    result = await t.execute(
        {
            "tasks": [{"role": "撰写员", "task": "写稿"}],
            "append_to_execution_id": "exec-host",
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert captured["execution_id"] == "exec-host"
    assert "r_old" in captured["node_ids"]
    assert len(captured["node_ids"]) == 2
    assert captured["seed"] == seed
    assert t._base_tool_context.execution_id == "exec-host"

    kinds = [e.type for e in t._sink._history]
    assert EventType.GRAPH_APPEND in kinds
    assert EventType.RUN_PLAN in kinds
    ga = next(e for e in t._sink._history if e.type is EventType.GRAPH_APPEND)
    assert ga.payload["host_message_id"] == "m-host"
    assert ga.payload["added_count"] == 1
    rp = next(e for e in t._sink._history if e.type is EventType.RUN_PLAN)
    assert rp.payload.get("host_message_id") == "m-host"
    assert "跨回合同图追加" in (result.output or "")


@pytest.mark.asyncio
async def test_delegate_append_resolves_depends_on_host_node(monkeypatch):
    """跨批 append：depends_on 宿主图已有 run_id → build 成功并保留边。"""
    register_graph_host("exec-host", "m-host")

    host_plan = RunPlan(
        nodes=[
            RunSpec(run_id="bt_l2_a", agent_id="bt_l2_a", role="调研A", task="查A"),
        ]
    )
    seed = {"bt_l2_a": RunState(phase=RunPhase.COMPLETED, content="done")}

    async def fake_resolve(*, conversation_id: str, execution_id: str) -> str | None:
        return "m-host"

    async def fake_load(host_message_id: str):
        return host_plan, seed

    async def fake_open_writer(**kwargs):  # noqa: ANN003
        return TurnJournalWriter(
            turn_id="m-host", conversation_id="c", trace_id=None, initial_seq=10
        )

    captured: dict[str, Any] = {}

    async def fake_drive(tool, plan, **kwargs):  # noqa: ANN001
        captured["deps"] = {
            n.run_id: list(n.depends_on) for n in plan.nodes if n.run_id != "bt_l2_a"
        }
        captured["node_ids"] = [n.run_id for n in plan.nodes]
        return ToolResult(tool_call_id="", success=True, output="ok")

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_host_message_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.load_host_plan_and_completed",
        fake_load,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.open_host_journal_writer",
        fake_open_writer,
    )
    monkeypatch.setattr("agentcore.tools.builtin.delegate.tool.drive", fake_drive)

    t = tool(Provider(["X"]))
    t._message_id = "m-new"
    t._conversation_id = "c"
    t._base_tool_context.execution_id = "exec-fresh"

    result = await t.execute(
        {
            "tasks": [
                {
                    "id": "l2_b",
                    "role": "写手",
                    "task": "基于上游写",
                    "depends_on": ["bt_l2_a"],
                }
            ],
            "append_to_execution_id": "exec-host",
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True, result.error
    assert "bt_l2_a" in captured["node_ids"]
    assert len(captured["deps"]) == 1
    assert list(captured["deps"].values())[0] == ["bt_l2_a"]


@pytest.mark.asyncio
async def test_delegate_append_latest_resolves_recent_graph(monkeypatch):
    """append_to_execution_id="latest" → 服务端解析到本对话最近一张协作图，语义同显式 id。"""
    host_plan = RunPlan(
        nodes=[RunSpec(run_id="r_old", agent_id="w_old", role="研究员", task="旧任务")]
    )
    seed = {"r_old": RunState(phase=RunPhase.COMPLETED, content="done")}
    latest_calls: dict[str, Any] = {}

    async def fake_latest(*, conversation_id: str, exclude_message_id=None) -> str | None:
        latest_calls["conversation_id"] = conversation_id
        latest_calls["exclude_message_id"] = exclude_message_id
        return "exec-host"

    async def fake_resolve(*, conversation_id: str, execution_id: str) -> str | None:
        assert execution_id == "exec-host"  # 解析结果走既有精确-id 路径
        return "m-host"

    async def fake_load(host_message_id: str):
        return host_plan, seed

    async def fake_open_writer(**kwargs):  # noqa: ANN003
        return TurnJournalWriter(
            turn_id="m-host", conversation_id="c", trace_id=None, initial_seq=10
        )

    captured: dict[str, Any] = {}

    async def fake_drive(tool, plan, **kwargs):  # noqa: ANN001
        captured["execution_id"] = kwargs.get("execution_id")
        return ToolResult(tool_call_id="", success=True, output="ok")

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_appendable_execution",
        fake_latest,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_host_message_id",
        fake_resolve,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.load_host_plan_and_completed",
        fake_load,
    )
    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.open_host_journal_writer",
        fake_open_writer,
    )
    monkeypatch.setattr("agentcore.tools.builtin.delegate.tool.drive", fake_drive)

    t = tool(Provider(["X"]))
    t._message_id = "m-new"
    t._conversation_id = "c"

    result = await t.execute(
        {
            "tasks": [{"role": "撰写员", "task": "写稿"}],
            "append_to_execution_id": "latest",
            "coordinate": False,
        },
        ctx(),
    )
    assert result.success is True
    assert latest_calls == {"conversation_id": "c", "exclude_message_id": "m-new"}
    assert captured["execution_id"] == "exec-host"
    # 口径与产品呈现一致 + 回显 execution_id。
    assert "已往上方协作图追加 1 名成员" in (result.output or "")
    assert "exec-host" in (result.output or "")
    ga = next(e for e in t._sink._history if e.type is EventType.GRAPH_APPEND)
    assert ga.payload["execution_id"] == "exec-host"
    assert ga.payload["host_message_id"] == "m-host"


@pytest.mark.asyncio
async def test_delegate_append_latest_without_graph_errors(monkeypatch):
    """latest 解析不到候选 → 显式错误回 CEO；禁止静默新建图（不发任何图事件）。"""

    async def fake_latest(*, conversation_id: str, exclude_message_id=None) -> str | None:
        return None

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_appendable_execution",
        fake_latest,
    )
    t = tool(Provider(["X"]))
    t._conversation_id = "c"
    result = await t.execute(
        {
            "tasks": [{"role": "撰写员", "task": "写稿"}],
            "append_to_execution_id": "latest",
        },
        ctx(),
    )
    assert result.success is False
    assert "没有可追加" in (result.error or "")
    assert "新建" in (result.error or "")
    kinds = [e.type for e in t._sink._history]
    assert EventType.GRAPH_APPEND not in kinds
    assert EventType.RUN_PLAN not in kinds


@pytest.mark.asyncio
async def test_delegate_append_rejected_for_nested_lead():
    """跨回合追加仅根协调者可用：嵌套 lead（depth>0）显式拒绝，防跨图串写。"""
    from agentcore.tools.builtin.delegate import DelegateTool
    from agentcore.tools.registry import ToolRegistry

    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=ctx(),
        depth=1,
    )
    result = await t.execute(
        {
            "tasks": [{"role": "撰写员", "task": "写稿"}],
            "append_to_execution_id": "latest",
        },
        ctx(),
    )
    assert result.success is False
    assert "根协调者" in (result.error or "")


@pytest.mark.asyncio
async def test_delegate_fresh_graph_echoes_execution_id(monkeypatch):
    """首次建图（不追加）：结果尾部回显本图 execution_id + latest 用法。"""

    async def fake_drive(tool, plan, **kwargs):  # noqa: ANN001
        return ToolResult(tool_call_id="", success=True, output="ok")

    monkeypatch.setattr("agentcore.tools.builtin.delegate.tool.drive", fake_drive)
    t = tool(Provider(["X"]))
    result = await t.execute(
        {"tasks": [{"role": "研究员", "task": "调研"}], "coordinate": False},
        ctx(),
    )
    assert result.success is True
    out = result.output or ""
    assert "【协作图】" in out
    assert "execution_id=`e`" in out  # conftest ctx() 的 execution_id
    assert 'append_to_execution_id="latest"' in out
    # 新图不承诺追加。
    assert "已往上方协作图追加" not in out


@pytest.mark.asyncio
async def test_delegate_nested_lead_gets_no_execution_id_echo(monkeypatch):
    """嵌套 lead 不能跨回合追加 → 不给它回显 execution_id 尾注。"""
    from agentcore.tools.builtin.delegate import DelegateTool
    from agentcore.tools.registry import ToolRegistry

    async def fake_drive(tool, plan, **kwargs):  # noqa: ANN001
        return ToolResult(tool_call_id="", success=True, output="ok")

    monkeypatch.setattr("agentcore.tools.builtin.delegate.tool.drive", fake_drive)
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=EventSink(),
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=ctx(),
        depth=1,
    )
    result = await t.execute(
        {"tasks": [{"role": "研究员", "task": "调研"}], "coordinate": False},
        ctx(),
    )
    assert result.success is True
    assert "【协作图】" not in (result.output or "")


@pytest.mark.asyncio
async def test_build_recent_graph_context_note(monkeypatch):
    """跨回合可见回显通道：有最近图 → <recent_team_graph> 注记；无图 → 空串（段落整体掉落）。"""
    from agentcore.runtime.delegate.graph_append import build_recent_graph_context

    async def fake_latest(*, conversation_id: str, exclude_message_id=None) -> str | None:
        return "exec-9"

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_appendable_execution",
        fake_latest,
    )
    note = await build_recent_graph_context(conversation_id="c")
    assert "<recent_team_graph>" in note
    assert "exec-9" in note
    assert "latest" in note

    async def fake_none(*, conversation_id: str, exclude_message_id=None) -> str | None:
        return None

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_appendable_execution",
        fake_none,
    )
    assert await build_recent_graph_context(conversation_id="c") == ""


@pytest.mark.asyncio
async def test_assemble_injects_recent_graph_note_into_ceo_prompt(monkeypatch):
    """回显跨回合可见：assemble 把 <recent_team_graph> 注入 CEO 系统提示易变尾（非 worker base）。"""
    from types import SimpleNamespace

    from agentcore.runtime.pipeline import run as run_mod
    from agentcore.runtime.pipeline.assemble import assemble_ceo_turn
    from agentcore.runtime.pipeline.prepare import PreparedTurn
    from agentcore.runtime.skills import build_system_skill_registry
    from agentcore.tools.registry import ToolRegistry

    note = "<recent_team_graph>\nexecution_id=`exec-42`\n</recent_team_graph>"

    async def fake_note(*, conversation_id: str, exclude_message_id=None) -> str:
        assert conversation_id == "c"
        assert exclude_message_id == "m-new"
        return note

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.build_recent_graph_context",
        fake_note,
    )

    def fake_toolset(**kwargs):  # noqa: ANN003
        return None, None, ToolRegistry()

    monkeypatch.setattr(run_mod, "_assemble_ceo_toolset", fake_toolset)

    prepared = PreparedTurn(
        llm=None,
        system_prompt="BASE",
        worker_base_prompt="WORKER_BASE",
        worker_tools=ToolRegistry(),
        skill_registry=build_system_skill_registry(),
        board_channel=None,
        base_tool_context=ctx(),
        vision_cost_sink=[],
        attachment_context="",
        memory_topics=[],
        bound_execution_id="e",
        execution_id_token=None,
    )
    assembled = await assemble_ceo_turn(
        prepared=prepared,
        conversation_id="c",
        user_message="hi",
        history=[],
        sink=EventSink(),
        backend=SimpleNamespace(location="server"),
        folder_id=None,
        memory_enabled=False,
        approvals_enabled=False,
        permission_axes=None,
        profiles=None,
        captain_run_id="cap",
        message_id="m-new",
        session_saver=None,
        session_loader=None,
        suspension_saver=None,
        suspension_deleter=None,
        x_client_platform=None,
    )
    assert note in assembled.chat_system_prompt
    # CEO-only：不进 worker base（prepared.worker_base_prompt 原样）。
    assert note not in prepared.worker_base_prompt


@pytest.mark.asyncio
async def test_delegate_append_unknown_execution_rejected(monkeypatch):
    clear_graph_host_registry()

    async def fake_resolve(*, conversation_id: str, execution_id: str) -> str | None:
        return None

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_host_message_id",
        fake_resolve,
    )
    t = tool(Provider(["X"]))
    t._conversation_id = "c"
    result = await t.execute(
        {
            "tasks": [{"role": "撰写员", "task": "写稿"}],
            "append_to_execution_id": "does-not-exist",
        },
        ctx(),
    )
    assert result.success is False
    assert "找不到" in (result.error or "")


def test_projection_cross_turn_keeps_runs_across_message_start():
    from agentcore.conformance.projection import project_turn
    from agentcore.conformance.vectors.multi_agent.cross_turn_append import (
        _multi_agent_cross_turn_append,
    )

    events = [
        {"type": e.type.value, "payload": e.payload, "timestamp": e.timestamp}
        for e in _multi_agent_cross_turn_append()
    ]
    projected = project_turn(events)
    assert projected["status"] == "completed"
    run_ids = {r["id"] for r in projected["runs"]}
    assert {"r1", "r2", "r3"} <= run_ids
    r3 = next(r for r in projected["runs"] if r["id"] == "r3")
    assert r3["status"] == "completed"
    process = projected["process"]
    assert any(s.get("kind") == "graph_append" for s in process)
    assert not any(s.get("kind") == "team" for s in process)
    assert "追加" in projected["content"] or "撰写" in projected["content"]
