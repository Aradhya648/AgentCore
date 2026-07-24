"""Multi-agent mid-flight user interjection vectors (协调插话 → CEO 路由)."""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    message_end,
    message_start,
    run_completed,
    run_plan,
    run_started,
    team_synthesis_preview,
    tool_use_end,
    tool_use_start,
    user_interjection,
)

from .._common import _CONV, _COST, _USAGE


def _agents_and_plan() -> tuple[list[dict], list[dict]]:
    agents = [
        {
            "id": "w1",
            "role": "研究员",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "撰写员",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写", "depends_on": []},
    ]
    return agents, plan_runs


def _multi_agent_user_interjection_handled() -> list[SSEEvent]:
    """插话入图处置：delivered 后 CEO 用 update_synthesis 承接，status 保持 delivered。"""
    agents, plan_runs = _agents_and_plan()
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排团队并行推进。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "研究员"}, {"role": "撰写员"}]},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="并行调研 + 撰写",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        user_interjection(
            interjection_id="inj1",
            execution_id="exec1",
            content="补充一点：结论里请点明成本对比。",
            status="delivered",
        ),
        tool_use_start(
            "syn1",
            "update_synthesis",
            {"draft": "已收到补充：成品会点明成本对比。"},
        ),
        tool_use_end(
            "syn1",
            "update_synthesis",
            success=True,
            output="已更新合成草稿（18 字），用户可见「进展中」预览。",
        ),
        team_synthesis_preview(
            execution_id="exec1",
            completed=0,
            total=2,
            headline="合成草稿更新 · 已完成 0/2",
            text="已收到补充：成品会点明成本对比。",
            workers=[],
            in_progress=True,
        ),
        run_completed(
            "r1",
            "w1",
            output_summary="完成调研",
            duration_ms=1000,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            "r2",
            "w2",
            output_summary="完成撰写",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队已完成。"),
        content_delta("团队已按你的补充交稿。"),
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
    ]


def _multi_agent_user_interjection_queued() -> list[SSEEvent]:
    """插话转排队：delivered → CEO queue_user_message → status=queued（同 id 保最新）。"""
    agents, plan_runs = _agents_and_plan()
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排团队并行推进。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "研究员"}, {"role": "撰写员"}]},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="并行调研 + 撰写",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        user_interjection(
            interjection_id="inj2",
            execution_id="exec1",
            content="另外帮我写一封生日贺卡，跟这个项目无关。",
            status="delivered",
        ),
        tool_use_start(
            "q1",
            "queue_user_message",
            {
                "interjection_id": "inj2",
                "reason": "与当前团队任务无关，已排到下一回合",
            },
        ),
        tool_use_end(
            "q1",
            "queue_user_message",
            success=True,
            output="已将插话转入对话级排队（位置 1/1）。",
        ),
        user_interjection(
            interjection_id="inj2",
            execution_id="exec1",
            content="另外帮我写一封生日贺卡，跟这个项目无关。",
            status="queued",
            note="与当前团队任务无关，已排到下一回合",
        ),
        run_completed(
            "r1",
            "w1",
            output_summary="完成调研",
            duration_ms=1000,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            "r2",
            "w2",
            output_summary="完成撰写",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队已完成。"),
        content_delta("当前任务已收口；你的贺卡请求已排队，下一回合处理。"),
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
    ]


def _multi_agent_user_interjection_with_attachments() -> list[SSEEvent]:
    """带附件插话：delivered SSE 携带 attachments 元数据（名字 + 路径 + 二进制标记）。"""
    agents, plan_runs = _agents_and_plan()
    att_meta = [
        {
            "name": "成本表.xlsx",
            "workspace_path": "attachments/成本表.xlsx",
            "binary": True,
        },
        {
            "name": "补充说明.md",
            "workspace_path": "attachments/补充说明.md",
            "binary": False,
        },
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排团队并行推进。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "研究员"}, {"role": "撰写员"}]},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="并行调研 + 撰写",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        user_interjection(
            interjection_id="inj-att",
            execution_id="exec1",
            content="请对照附件里的成本表再核一遍。",
            status="delivered",
            attachments=att_meta,
        ),
        tool_use_start(
            "syn1",
            "update_synthesis",
            {"draft": "已收到附件补充：会对照成本表核验。"},
        ),
        tool_use_end(
            "syn1",
            "update_synthesis",
            success=True,
            output="已更新合成草稿，用户可见「进展中」预览。",
        ),
        team_synthesis_preview(
            execution_id="exec1",
            completed=0,
            total=2,
            headline="合成草稿更新 · 已完成 0/2",
            text="已收到附件补充：会对照成本表核验。",
            workers=[],
            in_progress=True,
        ),
        run_completed(
            "r1",
            "w1",
            output_summary="完成调研",
            duration_ms=1000,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        run_completed(
            "r2",
            "w2",
            output_summary="完成撰写",
            duration_ms=800,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队已完成。"),
        content_delta("团队已按附件补充交稿。"),
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
    ]
