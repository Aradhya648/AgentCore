"""跨回合同图追加 conformance 向量。

第一回合建图完成 → 第二回合 ``append_to_execution_id`` 追加 → 追加批完成收口。
消费端契约：(a) 生长帧 ``host_message_id`` / 同 ``execution_id`` 归属旧图；
(b) 新回合 ``graph_append`` 锚点；(c) 刷新后宿主 journal 含完整生长、追加回合仅锚点。
"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    graph_append,
    message_end,
    message_start,
    run_completed,
    run_output_delta,
    run_plan,
    run_started,
    tool_use_end,
    tool_use_start,
)

from .._common import _CONV, _COST, _USAGE


def _multi_agent_cross_turn_append() -> list[SSEEvent]:
    """跨回合同图追加：m1 建图完成 → m2 追加成员 → 追加批完成；图收口不绑 m2 message_end。"""
    batch1_agents = [
        {
            "id": "w1",
            "role": "研究员",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "分析师",
            "thinking": True,
        },
    ]
    batch1_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研素材", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "分析结论", "depends_on": ["r1"]},
    ]
    batch2_agents = [
        {
            "id": "w3",
            "role": "撰写员",
            "thinking": True,
        },
    ]
    # 第二批 run_plan 为 merge 全量（含旧节点 + 新节点），与生产 plan_event 一致。
    batch2_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研素材", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "分析结论", "depends_on": ["r1"]},
        {"id": "r3", "agent_id": "w3", "task": "撰写文稿", "depends_on": []},
    ]
    return [
        # ── 回合 1：建图并完成 ──
        message_start("m1", conversation_id=_CONV),
        content_delta("先组队调研分析。"),
        tool_use_start(
            "dc1",
            "delegate",
            {
                "tasks": [{"role": "研究员"}, {"role": "分析师"}],
                "coordinate": False,
            },
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="调研分析",
            agents=batch1_agents,
            runs=batch1_runs,
        ),
        run_started("r1", "w1"),
        run_output_delta("r1", "w1", "素材就绪"),
        run_completed(
            "r1",
            "w1",
            output_summary="调研完成",
            duration_ms=900,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_started("r2", "w2"),
        run_output_delta("r2", "w2", "分析定稿"),
        run_completed(
            "r2",
            "w2",
            output_summary="分析完成",
            duration_ms=1100,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队完成 2 项任务。"),
        content_delta(" 第一轮结论已汇总。"),
        message_end(FinishReason.END_TURN, input_tokens=4000, output_tokens=700, cost=_COST),
        # ── 回合 2：跨回合同图追加 ──
        message_start("m2", conversation_id=_CONV),
        content_delta("再往上一张图加一位撰写员。"),
        tool_use_start(
            "dc2",
            "delegate",
            {
                "tasks": [{"role": "撰写员", "task": "撰写文稿"}],
                "append_to_execution_id": "exec1",
                "coordinate": False,
            },
        ),
        graph_append(
            execution_id="exec1",
            host_message_id="m1",
            append_message_id="m2",
            added_count=1,
            roles=["撰写员"],
            added_run_ids=["r3"],
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="调研分析撰写",
            agents=[*batch1_agents, *batch2_agents],
            runs=batch2_runs,
            host_message_id="m1",
        ),
        run_started("r3", "w3"),
        run_output_delta("r3", "w3", "成稿"),
        run_completed(
            "r3",
            "w3",
            output_summary="撰写完成",
            duration_ms=1000,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        tool_use_end(
            "dc2",
            "delegate",
            success=True,
            output="【跨回合同图追加】已往协作图追加 1 名成员。",
        ),
        content_delta(" 已追加撰写员，图上继续更新。"),
        # m2 收口；图完成态由 execution 自身 run 终态决定（本向量中 r3 已完成）。
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
    ]
