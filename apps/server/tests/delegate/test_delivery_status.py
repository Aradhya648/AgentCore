"""交付状态结构化（能力闸门与交付诚实性）：delivery_status 构建与发射单元测试。"""

from __future__ import annotations

import pytest

from agentcore.core.types import AutonomyPolicy
from agentcore.runtime.delegate.delivery_status import (
    build_delivery_status,
    maybe_emit_delivery_status,
)
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState
from agentcore.tools.builtin.delegate import DelegateTool
from agentcore.tools.registry import ToolRegistry
from tests.delegate.conftest import LocalBackend, Provider, ctx, local_ctx


def _plan(*specs: RunSpec) -> RunPlan:
    return RunPlan(nodes=list(specs))


def test_pure_prose_success_stays_silent():
    plan = _plan(RunSpec(run_id="w1", task="调研", role="研究员"))
    results = {"w1": RunState(phase=RunPhase.COMPLETED, content="综述正文")}
    assert build_delivery_status(plan, results, execution_id="e") is None


def test_all_files_delivered_no_gaps():
    plan = _plan(RunSpec(run_id="w1", task="写讲稿", role="撰写"))
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="已落盘",
            files_touched=["讲稿.md", "notes/大纲.md"],
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e1")
    assert payload is not None
    assert payload["state"] == "delivered"
    assert payload["delivered_files"] == ["讲稿.md", "notes/大纲.md"]
    assert payload["gaps"] == []
    assert payload["actions"] == []
    assert "已交付 2 个文件" in payload["summary"]


def test_partial_with_worker_gaps_and_degraded_debrief():
    # collect_worker_gaps 信号（warnings + degraded 交接）折成 gap 行。
    plan = _plan(
        RunSpec(run_id="w1", task="生成课件", role="课件工程师"),
        RunSpec(run_id="w2", task="写讲稿", role="撰写", depends_on=["w1"]),
    )
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="脚本已写",
            files_touched=["build_pptx.py"],
            warnings=["声明产物 course.pptx 未在工作区找到"],
            debrief={"summary": "引擎合成", "degraded": True},
        ),
        "w2": RunState(phase=RunPhase.COMPLETED, content="讲稿", files_touched=["讲稿.md"]),
    }
    payload = build_delivery_status(plan, results, execution_id="e2")
    assert payload is not None
    assert payload["state"] == "partial"
    assert set(payload["delivered_files"]) == {"build_pptx.py", "讲稿.md"}
    descriptions = [g["description"] for g in payload["gaps"]]
    assert any("course.pptx" in d for d in descriptions)
    assert any("降级合成" in d for d in descriptions)
    assert all(g["role"] == "课件工程师" for g in payload["gaps"])
    assert any(g.get("reason") == "degraded_handoff" for g in payload["gaps"])


def test_blocked_with_criteria_gap_and_bind_action_on_cloud():
    # 「验收」批次级缺口 + 云端无执行环境 → bind_local_folder 行动项（复用单一真相源判定）。
    plan = _plan(RunSpec(run_id="w1", task="运行脚本生成 course.pptx", role="课件工程师"))
    results = {"w1": RunState(phase=RunPhase.COMPLETED, content="只有文字")}
    payload = build_delivery_status(
        plan,
        results,
        execution_id="e3",
        backend=ctx().backend,
        criteria_gaps=["尚无 worker 成功运行 code_execute / test_run 验证代码"],
    )
    assert payload is not None
    assert payload["state"] == "blocked"
    assert payload["delivered_files"] == []
    assert payload["gaps"][0]["role"] == "验收"
    assert payload["actions"] and payload["actions"][0]["kind"] == "bind_local_folder"
    assert "未能交付" in payload["summary"]


def test_no_bind_action_on_local_backend():
    plan = _plan(RunSpec(run_id="w1", task="运行脚本生成 course.pptx", role="工程师"))
    results = {"w1": RunState(phase=RunPhase.FAILED, error="超时")}
    payload = build_delivery_status(
        plan, results, execution_id="e4", backend=LocalBackend()
    )
    assert payload is not None
    assert payload["state"] == "blocked"
    assert payload["actions"] == []
    assert "失败" in payload["gaps"][0]["description"]


def test_failed_skipped_cancelled_nodes_become_gaps():
    plan = _plan(
        RunSpec(run_id="a", task="t", role="A"),
        RunSpec(run_id="b", task="t", role="B"),
        RunSpec(run_id="c", task="t", role="C"),
    )
    results = {
        "a": RunState(phase=RunPhase.FAILED, error="炸了"),
        "b": RunState(phase=RunPhase.SKIPPED),
        "c": RunState(phase=RunPhase.CANCELLED),
    }
    payload = build_delivery_status(plan, results, execution_id="e5")
    assert payload is not None
    by_role = {g["role"]: g["description"] for g in payload["gaps"]}
    assert "失败：炸了" in by_role["A"]
    assert "未执行" in by_role["B"]
    assert "取消" in by_role["C"]


def test_cancelled_node_with_completed_revision_is_not_a_gap():
    # 跑一半改方向：原 run 取消但热修修订完成 → 不算缺口；修订产物计入已交付。
    plan = _plan(RunSpec(run_id="w1", task="写页面", role="前端"))
    results = {
        "w1": RunState(phase=RunPhase.CANCELLED),
        "w1_rev1": RunState(
            phase=RunPhase.COMPLETED, content="重写完成", files_touched=["index.html"]
        ),
    }
    payload = build_delivery_status(plan, results, execution_id="e6")
    assert payload is not None
    assert payload["state"] == "delivered"
    assert payload["gaps"] == []
    assert payload["delivered_files"] == ["index.html"]


def test_maybe_emit_gates_and_emits():
    sink = EventSink()
    prose_plan = _plan(RunSpec(run_id="w1", task="调研", role="研究员"))
    maybe_emit_delivery_status(
        sink,
        prose_plan,
        {"w1": RunState(phase=RunPhase.COMPLETED, content="正文")},
        execution_id="e",
    )
    assert not any(e.type is EventType.DELIVERY_STATUS for e in sink._history)

    files_plan = _plan(RunSpec(run_id="w1", task="写文件", role="工程师"))
    maybe_emit_delivery_status(
        sink,
        files_plan,
        {
            "w1": RunState(
                phase=RunPhase.COMPLETED, content="ok", files_touched=["a.md"]
            )
        },
        execution_id="e7",
    )
    events = [e for e in sink._history if e.type is EventType.DELIVERY_STATUS]
    assert len(events) == 1
    assert events[0].payload["execution_id"] == "e7"
    assert events[0].payload["state"] == "delivered"


def test_qa_deferred_budget_emits_website_verify_action():
    from agentcore.runtime.runs.types import Deliverable

    plan = _plan(
        RunSpec(
            run_id="qa",
            role="页面 QA",
            task="独立【整页验收】站点【GEO 官网】…",
            deliverable=Deliverable(
                name="QA",
                form="files",
                artifacts=["site/QA.md"],
                visual_critic=True,
            ),
        )
    )
    results = {
        "qa": RunState(
            phase=RunPhase.SKIPPED,
            delivery_gaps=[
                {
                    "description": "整页验收波未跑（本回合预算用尽）",
                    "reason": "qa_deferred_budget",
                }
            ],
            files_touched=[],
        )
    }
    # Need a delivered file elsewhere so state is partial (or gaps alone → blocked).
    plan.nodes.insert(
        0,
        RunSpec(run_id="s0", role="区0", task="分区"),
    )
    results["s0"] = RunState(
        phase=RunPhase.COMPLETED, files_touched=["site/index.html"]
    )
    payload = build_delivery_status(plan, results, execution_id="e-qa")
    assert payload is not None
    assert payload["state"] == "partial"
    assert any(a.get("kind") == "website_verify" for a in payload["actions"])
    action = next(a for a in payload["actions"] if a["kind"] == "website_verify")
    assert "build_website_verify" in action["prompt"]
    assert "GEO 官网" in action["prompt"]
    assert "site=" in action["prompt"]


@pytest.mark.asyncio
async def test_execute_emits_delivery_status_on_criteria_unmet():
    # drive 接线（验收未满足路径）：code_verified 未被满足 → gap 消息之外，同回合发出
    # 结构化 delivery_status（状态 blocked、验收缺口）。本地后端（闸门放行）+ FULL_AUTO。
    sink = EventSink()
    t = DelegateTool(
        llm=Provider(["X"]),
        sink=sink,
        system_prompt="SYS",
        user_message="原始请求",
        history=[],
        tools=ToolRegistry(),
        base_tool_context=local_ctx(),
        autonomy_policy=AutonomyPolicy.FULL_AUTO,
    )
    result = await t.execute(
        {
            "tasks": [{"role": "工程师", "task": "修好构建脚本"}],
            "completion_criteria": "code_verified",
            "coordinate": False,
        },
        local_ctx(),
    )
    assert result.success is True
    assert "完成条件未满足" in result.output
    events = [e for e in sink._history if e.type is EventType.DELIVERY_STATUS]
    assert len(events) == 1
    assert events[0].payload["state"] == "blocked"
    assert events[0].payload["gaps"][0]["role"] == "验收"
