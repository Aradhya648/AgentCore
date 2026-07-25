"""辩论编排 SSE 事件与主持人计费。"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from agentcore.runtime.debate import DebateConfig
from agentcore.runtime.debate.constants import FORM_LABELS
from agentcore.runtime.events import run_completed, run_plan

if TYPE_CHECKING:
    from agentcore.runtime.debate import DebateResult
    from agentcore.runtime.debate.moderator import Moderator
    from agentcore.tools.builtin.debate.tool import DebateTool


def debate_act_payload(tool: DebateTool) -> dict[str, Any]:
    """幕声明：独立辩论 = act-1；挂宿主生长 = 下一幕（anchor=汇总员）。"""
    act_id = getattr(tool, "_debate_act_id", None) or "act-1"
    act: dict[str, Any] = {"act_id": act_id, "kind": "debate"}
    title = getattr(tool, "_debate_act_title", None)
    if title:
        act["title"] = title
    anchor = getattr(tool, "_debate_anchor_run_id", None)
    if anchor:
        act["anchor_run_id"] = anchor
    authorized_by = getattr(tool, "_debate_authorized_by", None)
    if authorized_by in ("stage_card", "auto", "preview"):
        act["authorized_by"] = authorized_by
    return act


def moderator_plan_event(
    tool: DebateTool, execution_id: str, moderator_run_id: str, config: DebateConfig
):
    """声明主持人节点（CEO 之下、辩手之上的编排角色）。

    独立辩论：主持人 ``parent_run_id`` 引用 CEO captain（节点不在图）。
    挂宿主新幕：``parent_run_id`` = 汇总员（图即因果：命题卡出自汇总员）。
    """
    label = FORM_LABELS.get(config.form, "辩论")
    parent = getattr(tool, "_debate_graph_parent_run_id", None) or tool._captain_run_id
    host_message_id = getattr(tool, "_debate_host_message_id", None)
    agents: list[dict[str, Any]] = [
        {
            "id": moderator_run_id,
            "role": "主持人",
            # 主持人是工具内确定性编排循环（§7.1）：从不对本节点发 run_reasoning_delta，
            # thinking 必须如实声明 False——前端详情面板据此不渲染「思考中」占位。
            "thinking": False,
        }
    ]
    runs: list[dict[str, Any]] = [
        {
            "id": moderator_run_id,
            "agent_id": moderator_run_id,
            "task": f"主持{label}：{config.motion[:60]}",
            "depends_on": [],
            "parent_run_id": parent,
        }
    ]
    return run_plan(
        execution_id=execution_id,
        plan_type="debate",
        task_summary=f"{label}：{config.motion[:60]}",
        agents=agents,
        runs=runs,
        host_message_id=host_message_id,
        act=debate_act_payload(tool),
    )


def side_card(tool: DebateTool, node) -> dict[str, Any]:
    return {
        "id": node.agent_id,
        "role": node.role,
        "thinking": node.thinking,
    }


def run_payload(node) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": node.run_id,
        "agent_id": node.agent_id,
        "task": node.task,
        "depends_on": node.depends_on,
        "parent_run_id": node.parent_run_id,
    }
    if node.stance:
        payload["stance"] = node.stance
    if node.group:
        payload["group"] = node.group
    if node.round:
        payload["round"] = node.round
    return payload


def account_moderator(
    tool: DebateTool,
    moderator: Moderator,
    moderator_run_id: str,
    model: str,
    result: DebateResult,
    duration_ms: int,
) -> None:
    """主持人节点收尾：emit run_completed（耗时 + 成本 + 「N 轮·收敛归因」概览，团队图据此
    标完成），并把主持人自身 LLM 调用（议题 / 裁判 / 小结 / 简报）折算成一条主持人节点账目。"""
    from agentcore.llm.pricing import calculate_cost
    from agentcore.runtime.costing import ROLE_ARENA
    from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState

    usage = moderator.usage
    cost = calculate_cost(model, usage)
    summary = result.node_summary
    tool._sink.emit(
        run_completed(
            moderator_run_id,
            moderator_run_id,
            output_summary=summary,
            duration_ms=duration_ms,
            role="主持人",
            model=model,
            usage=usage.as_dict(),
            cost=asdict(cost),
        )
    )
    if usage.total_tokens <= 0:
        return  # 无 LLM 用量（极端）则不另记账目，但主持人节点已 emit 完成态。
    spec = RunSpec(
        run_id=moderator_run_id,
        agent_id=moderator_run_id,
        task="主持辩论",
        role="主持人",
    )
    state = RunState(
        phase=RunPhase.COMPLETED,
        model=model,
        usage=usage.as_dict(),
        cost=asdict(cost),
        rounds=moderator.llm_rounds,
    )
    tool._acc.add_run_cost(
        spec, state, parent_run_id=tool._captain_run_id, role=ROLE_ARENA
    )
    tool._acc.add_usage(usage.as_dict())
