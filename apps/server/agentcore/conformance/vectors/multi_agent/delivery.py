"""Multi-agent delivery-status vectors（交付状态结构化：已交付 / 缺口 / 待用户操作）."""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    delivery_status,
    message_end,
    message_start,
    run_completed,
    run_plan,
    run_started,
    tool_use_end,
    tool_use_start,
)

from .._common import _CONV, _COST, _USAGE


def _multi_agent_delivery_status_partial() -> list[SSEEvent]:
    """交付对账·部分交付：脚本落盘但可播放 pptx 未生成（云端无执行环境）。

    delivery_status 同 execution_id 保最新——先发 blocked（验收未满足即时对账）、
    后发 partial（补写脚本后的最终对账），fold 只留最后一条；gaps + actions
    （bind_local_folder）随卡重建。
    """
    agents = [
        {
            "id": "w1",
            "role": "课件工程师",
            "thinking": True,
        },
        {
            "id": "w2",
            "role": "讲稿撰写",
            "thinking": True,
        },
    ]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "用 python-pptx 生成课件", "depends_on": []},
        {"id": "r2", "agent_id": "w2", "task": "撰写逐页讲稿", "depends_on": []},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("我来安排团队制作课件。"),
        tool_use_start(
            "dc1",
            "delegate",
            {"tasks": [{"role": "课件工程师"}, {"role": "讲稿撰写"}]},
        ),
        run_plan(
            execution_id="exec1",
            plan_type="multi_agent",
            task_summary="生成课件 + 讲稿",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        run_started("r2", "w2"),
        delivery_status(
            execution_id="exec1",
            state="blocked",
            summary="未能交付：1 项缺口",
            delivered_files=[],
            gaps=[{"role": "验收", "description": "尚无 worker 成功运行 code_execute / test_run 验证代码"}],
            actions=[
                {
                    "kind": "bind_local_folder",
                    "description": "本回合为云端会话、未装配执行环境：绑定本地文件夹后可在本机运行生成。",
                }
            ],
        ),
        run_completed(
            "r1",
            "w1",
            output_summary="生成脚本已落盘（未运行验证）",
            duration_ms=1200,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
            output_files=["build_pptx.py"],
        ),
        run_completed(
            "r2",
            "w2",
            output_summary="逐页讲稿已落盘",
            duration_ms=900,
            role="member",
            model="deepseek-v4-flash",
            usage=_USAGE,
            cost=_COST,
            output_files=["讲稿.md"],
        ),
        delivery_status(
            execution_id="exec1",
            state="partial",
            summary="已交付 2 个文件；1 项缺口",
            delivered_files=["build_pptx.py", "讲稿.md"],
            gaps=[
                {
                    "role": "课件工程师",
                    "description": "course.pptx 未生成（云端无执行环境，脚本未运行）",
                    "reason": "token_budget",
                }
            ],
            actions=[
                {
                    "kind": "bind_local_folder",
                    "description": "本回合为云端会话、未装配执行环境：绑定本地文件夹后可在本机运行生成。",
                }
            ],
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队已完成。"),
        content_delta("脚本与讲稿已就绪；pptx 需绑定本地文件夹后在本机生成。"),
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
    ]
