"""retry-failed seed remap + seeded-completion replay + latest 报错文案分支。

覆盖两个已定案 bug 的修复（均在 delegate 工具侧）：
1. retry_seed 按 raw 尾缀重映射到本回合新计划的同 raw 节点（数字位置号不映射、不命中丢弃），
   命中节点被 WaveScheduler 跳过、并在本回合如实补发完成态事件。
2. append_to_execution_id="latest" 解析失败时，按「本回合是否已有活跃协调会话」分两种引导文案。
"""

from __future__ import annotations

from typing import Any

import pytest

from agentcore.runtime.delegate.retry_remap import (
    _raw_suffix,
    remap_retry_seed,
    replay_seeded_completed,
)
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.facts import TurnFactLog, current_fact_log
from agentcore.runtime.runs import build_run_plan
from agentcore.runtime.runs.types import RunPhase, RunState
from agentcore.tools.protocol import ToolResult
from tests.delegate.conftest import Provider, ctx, tool


class CaptureSink(EventSink):
    """EventSink that also records every emitted event (bypasses history coalescing)."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list = []

    def emit(self, event) -> None:  # noqa: ANN001
        self.events.append(event)
        super().emit(event)


def _dag_plan(prefix: str, tasks: list[dict[str, Any]] | None = None):
    plan, errors = build_run_plan(
        tasks
        or [
            {"id": "researcher", "role": "研究员", "task": "调研"},
            {"id": "writer", "role": "写手", "task": "撰写", "depends_on": ["researcher"]},
        ],
        valid_tools=set(),
        id_prefix=prefix,
    )
    assert not errors, errors
    return plan


# ────────────────────────── raw 尾缀提取 ──────────────────────────


def test_raw_suffix_extraction():
    # uuid4 的连字符不含下划线 → maxsplit=2 干净切出 raw（raw 自身可带下划线）。
    assert _raw_suffix("del_1b2c-3d4e_researcher") == "researcher"
    assert _raw_suffix("del_uuid_writer_final") == "writer_final"
    assert _raw_suffix("add_uuid_n0") == "n0"
    assert _raw_suffix("del_uuid_1") == "1"
    # 非铸造形态（captain / 手工 id）→ None。
    assert _raw_suffix("captain") is None
    assert _raw_suffix("cap_only") is None


# ────────────────────────── remap 纯函数 ──────────────────────────


def test_remap_hits_same_raw_dag_node():
    plan = _dag_plan("del_new")
    seed = {"del_old_researcher": RunState(phase=RunPhase.COMPLETED, content="R done")}
    result = remap_retry_seed(seed, plan, prefix="del_new")
    assert result.hits == [("del_old_researcher", "del_new_researcher")]
    assert set(result.seed) == {"del_new_researcher"}
    assert result.seed["del_new_researcher"].content == "R done"
    assert not result.dropped_numeric
    assert not result.dropped_no_match
    assert not result.dropped_ambiguous


def test_remap_partial_hit_and_unmatched_drop():
    plan = _dag_plan("del_new")
    seed = {
        "del_old_researcher": RunState(phase=RunPhase.COMPLETED, content="R"),
        "del_old_ghost": RunState(phase=RunPhase.COMPLETED, content="G"),
    }
    result = remap_retry_seed(seed, plan, prefix="del_new")
    assert set(result.seed) == {"del_new_researcher"}
    assert result.dropped_no_match == ["del_old_ghost"]


def test_remap_skips_numeric_raw_flat_batch():
    # 无依赖批 → builder 铸 {prefix}_{n} 数字位置号；语义不可靠、不映射。
    plan = build_run_plan(
        [{"role": "A", "task": "t1"}, {"role": "B", "task": "t2"}],
        valid_tools=set(),
        id_prefix="del_new",
    )[0]
    assert [n.run_id for n in plan.nodes] == ["del_new_1", "del_new_2"]
    seed = {"del_old_1": RunState(phase=RunPhase.COMPLETED, content="x")}
    result = remap_retry_seed(seed, plan, prefix="del_new")
    assert result.seed == {}
    assert result.dropped_numeric == ["del_old_1"]
    assert not result.hits


def test_remap_ambiguous_collision_keeps_first():
    # 旧回合多批复用同 raw（del_a_writer / del_b_writer）→ 映到同一新节点：保第一条、丢其余。
    plan = _dag_plan(
        "del_new",
        tasks=[
            {"id": "writer", "role": "写手", "task": "撰写"},
            {"id": "editor", "role": "编辑", "task": "编辑", "depends_on": ["writer"]},
        ],
    )
    seed = {
        "del_a_writer": RunState(phase=RunPhase.COMPLETED, content="A"),
        "del_b_writer": RunState(phase=RunPhase.COMPLETED, content="B"),
    }
    result = remap_retry_seed(seed, plan, prefix="del_new")
    assert set(result.seed) == {"del_new_writer"}
    assert result.seed["del_new_writer"].content == "A"
    assert result.dropped_ambiguous == ["del_b_writer"]


def test_remap_empty_seed_is_noop():
    plan = _dag_plan("del_new")
    result = remap_retry_seed({}, plan, prefix="del_new")
    assert result.seed == {}
    assert not result.hits


# ────────────────────────── seeded 完成态补发 ──────────────────────────


def test_replay_seeded_completed_emits_full_presentation():
    plan = _dag_plan("del_new")
    seed = {
        "del_new_researcher": RunState(
            phase=RunPhase.COMPLETED,
            content="研究产出",
            reasoning="思考全文",
            model="m-x",
            duration_ms=1234,
            usage={"input": 10, "output": 5},
            cost={"total": 42},
            debrief={"summary": "结论一句话"},
            files_touched=["out/report.md"],
        )
    }
    sink = CaptureSink()
    log = TurnFactLog()
    tok = current_fact_log.set(log)
    try:
        replay_seeded_completed(sink, plan, seed)
    finally:
        current_fact_log.reset(tok)

    types = [e.type for e in sink.events]
    assert EventType.RUN_STARTED in types
    assert EventType.RUN_REASONING_DELTA in types
    assert EventType.RUN_OUTPUT_DELTA in types
    assert EventType.RUN_COMPLETED in types
    # 仅补发 seeded 节点（writer 未 seed → 不补发）。
    started_ids = [e.payload["run_id"] for e in sink.events if e.type is EventType.RUN_STARTED]
    assert started_ids == ["del_new_researcher"]
    rc = next(e for e in sink.events if e.type is EventType.RUN_COMPLETED)
    # payload 形状与执行器 run_completed 一致。
    assert rc.payload["run_id"] == "del_new_researcher"
    assert rc.payload["output_summary"] == "结论一句话"
    assert rc.payload["duration_ms"] == 1234
    assert rc.payload["model"] == "m-x"
    assert rc.payload["output_files"] == ["out/report.md"]
    assert rc.payload["role"] == "member"

    # 耐久 message_final fact 落库 → 冷重载经 completed_from_journal 重建 seed + 合成 delta 重建正文。
    entries = log.entries()
    finals = [
        e
        for e in entries
        if e["kind"] == "message_final" and e["payload"].get("run_id") == "del_new_researcher"
    ]
    assert len(finals) == 1
    assert finals[0]["payload"]["phase"] == "completed"
    assert finals[0]["payload"]["content"] == "研究产出"


def test_replay_skips_non_completed_and_absent():
    plan = _dag_plan("del_new")
    seed = {
        # FAILED seed 不应被当作完成态补发（正常 retry seed 只含 COMPLETED，这里防御）。
        "del_new_researcher": RunState(phase=RunPhase.FAILED, error="boom"),
    }
    sink = CaptureSink()
    replay_seeded_completed(sink, plan, seed)
    assert not sink.events


# ────────────────────────── execute 集成：remap 流入 drive + 补发 ──────────────────────────


@pytest.mark.asyncio
async def test_execute_retry_seed_remapped_into_drive_and_replayed(monkeypatch):
    from agentcore.runtime.retry import retry_seed

    captured: dict[str, Any] = {}

    async def fake_drive(tool, plan, **kwargs):  # noqa: ANN001
        captured["seed"] = kwargs.get("seed_completed")
        captured["node_ids"] = [n.run_id for n in plan.nodes]
        return ToolResult(tool_call_id="", success=True, output="ok")

    monkeypatch.setattr("agentcore.tools.builtin.delegate.tool.drive", fake_drive)

    t = tool(Provider(["X"]))
    # 上一回合已成功 researcher（旧前缀 key）；本回合 writer 失败要补跑。
    seed = {"del_old_researcher": RunState(phase=RunPhase.COMPLETED, content="R")}
    tok = retry_seed.set(seed)
    try:
        result = await t.execute(
            {
                "tasks": [
                    {"id": "researcher", "role": "研究员", "task": "调研"},
                    {"id": "writer", "role": "写手", "task": "撰写", "depends_on": ["researcher"]},
                ],
                "coordinate": False,
            },
            ctx(),
        )
    finally:
        retry_seed.reset(tok)

    assert result.success is True
    seed_passed = captured["seed"]
    assert seed_passed is not None and len(seed_passed) == 1
    (new_key,) = tuple(seed_passed)
    # 重映射到本回合新前缀的同 raw 节点，且该 key 属于新计划。
    assert new_key.endswith("_researcher")
    assert new_key in captured["node_ids"]
    assert seed_passed[new_key].content == "R"
    # 命中节点在本回合事件流补发 run_started / run_completed（否则前端图卡 pending）。
    started = [e for e in t._sink._history if e.type is EventType.RUN_STARTED]
    completed = [e for e in t._sink._history if e.type is EventType.RUN_COMPLETED]
    assert any(e.payload["run_id"] == new_key for e in started)
    assert any(e.payload["run_id"] == new_key for e in completed)
    # retry_seed 消费后清空，避免同回合二次 delegate 继承陈旧 seed。
    assert retry_seed.get(None) is None


@pytest.mark.asyncio
async def test_execute_retry_seed_numeric_all_rerun(monkeypatch):
    # flat 批（数字位置号）→ 不映射 → seed_completed 为 None → 全量重跑、无补发。
    from agentcore.runtime.retry import retry_seed

    captured: dict[str, Any] = {}

    async def fake_drive(tool, plan, **kwargs):  # noqa: ANN001
        captured["seed"] = kwargs.get("seed_completed")
        return ToolResult(tool_call_id="", success=True, output="ok")

    monkeypatch.setattr("agentcore.tools.builtin.delegate.tool.drive", fake_drive)

    t = tool(Provider(["X"]))
    seed = {"del_old_1": RunState(phase=RunPhase.COMPLETED, content="R")}
    tok = retry_seed.set(seed)
    try:
        result = await t.execute(
            {"tasks": [{"role": "A", "task": "t1"}, {"role": "B", "task": "t2"}], "coordinate": False},
            ctx(),
        )
    finally:
        retry_seed.reset(tok)

    assert result.success is True
    assert captured["seed"] is None
    assert not [e for e in t._sink._history if e.type is EventType.RUN_COMPLETED]


# ────────────────────────── latest 报错文案两分支 ──────────────────────────


@pytest.mark.asyncio
async def test_latest_failure_without_active_coordination_keeps_new_team_wording(monkeypatch):
    async def fake_latest(*, conversation_id: str, exclude_message_id=None) -> str | None:
        return None

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_appendable_execution",
        fake_latest,
    )
    t = tool(Provider(["X"]))
    t._conversation_id = "c"
    result = await t.execute(
        {"tasks": [{"role": "写手", "task": "写稿"}], "append_to_execution_id": "latest"},
        ctx(),
    )
    assert result.success is False
    assert "没有可追加" in (result.error or "")
    assert "新建团队执行" in (result.error or "")
    # 无活跃会话分支不给「同回合追加」引导。
    assert "同回合追加无需" not in (result.error or "")
    assert result.contract_failure is True


@pytest.mark.asyncio
async def test_latest_failure_with_active_coordination_guides_merge(monkeypatch):
    from agentcore.runtime.coordination.session import (
        CoordinationSession,
        clear_active_coordination,
        set_active_coordination,
    )

    async def fake_latest(*, conversation_id: str, exclude_message_id=None) -> str | None:
        return None

    monkeypatch.setattr(
        "agentcore.runtime.delegate.graph_append.resolve_latest_appendable_execution",
        fake_latest,
    )
    t = tool(Provider(["X"]))
    t._conversation_id = "c"
    # 本回合已有活跃协调会话，键为本回合 execution_id（conftest ctx() 为 "e"）。
    set_active_coordination(CoordinationSession(execution_id="e", total_workers=2))
    try:
        result = await t.execute(
            {"tasks": [{"role": "写手", "task": "写稿"}], "append_to_execution_id": "latest"},
            ctx(),
        )
    finally:
        clear_active_coordination("e")

    assert result.success is False
    assert "同回合追加无需" in (result.error or "")
    assert "自动并入当前协作图" in (result.error or "")
    assert result.contract_failure is True
    # 不新建、不发任何图事件。
    kinds = [e.type for e in t._sink._history]
    assert EventType.GRAPH_APPEND not in kinds
    assert EventType.RUN_PLAN not in kinds
