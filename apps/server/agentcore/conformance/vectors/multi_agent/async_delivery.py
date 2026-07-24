"""异步团队产出投递：execution_detached / execution_completed 协议向量。"""

from __future__ import annotations

from agentcore.runtime.events import (
    FinishReason,
    SSEEvent,
    content_delta,
    execution_completed,
    execution_detached,
    message_end,
    message_start,
    run_completed,
    run_plan,
    run_started,
    tool_use_end,
    tool_use_start,
)

from .._common import _CONV, _COST, _USAGE


def _multi_agent_execution_detached_completed() -> list[SSEEvent]:
    """后台转出 + 完成后：v1 fold no-op；golden 仅确认事件可过 payload 校验与重放不炸。

    覆盖 DURABLE 处置门禁；前端呈现另行委派。
    """
    agents = [{"id": "w1", "role": "研究员", "thinking": True}]
    plan_runs = [
        {"id": "r1", "agent_id": "w1", "task": "调研", "depends_on": []},
    ]
    return [
        message_start("m1", conversation_id=_CONV),
        content_delta("已派出团队，我先收口；队员后台继续。"),
        tool_use_start("dc1", "delegate", {"tasks": [{"role": "研究员"}]}),
        run_plan(
            execution_id="exec-bg",
            plan_type="multi_agent",
            task_summary="后台调研",
            agents=agents,
            runs=plan_runs,
        ),
        run_started("r1", "w1"),
        execution_detached(
            execution_id="exec-bg",
            conversation_id=_CONV,
            completed=0,
            total=1,
            reason="turn_released",
            host_turn_id="m1",
        ),
        tool_use_end("dc1", "delegate", success=True, output="团队已启动"),
        message_end(FinishReason.END_TURN, input_tokens=2000, output_tokens=400, cost=_COST),
        # 后台完成后的宿主 journal 续写（同 turn_id 重放）。
        run_completed(
            "r1",
            "w1",
            output_summary="调研完成",
            duration_ms=800,
            role="member",
            model="test",
            usage=_USAGE,
            cost=_COST,
        ),
        execution_completed(
            execution_id="exec-bg",
            conversation_id=_CONV,
            completed=1,
            total=1,
            host_turn_id="m1",
        ),
    ]


def _multi_agent_execution_detached_harvest_settle() -> list[SSEEvent]:
    """detached settle 全链路：execution_detached → execution_completed → 收口回合开流。

    收口回合是新 message_start（系统合成用户消息之后的 CEO 终稿）；v1 fold 对
    execution_* 仍 no-op，本向量锁定「收口回合可投影」契约。
    """
    return [
        *_multi_agent_execution_detached_completed(),
        # 收口回合（支柱 C）：新助手消息承载终稿。
        message_start("m-harvest", conversation_id=_CONV),
        content_delta("后台调研结论如下：……"),
        message_end(FinishReason.END_TURN, input_tokens=900, output_tokens=300, cost=_COST),
    ]
