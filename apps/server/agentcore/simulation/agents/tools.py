"""SimAgent action tools — mutate in-memory world, no filesystem side effects."""

from __future__ import annotations

from typing import Any

from agentcore.core.types import ToolCategory, ToolEffect
from agentcore.simulation.world.locations import LOCATIONS, position_for_location
from agentcore.simulation.world.state import WorldState
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry


class _SimActionTool:
    def __init__(self, world: WorldState, *, name: str, description: str, parameters: dict) -> None:
        self._world = world
        self._schema = ToolSchema(
            name=name,
            description=description,
            parameters=parameters,
            category=ToolCategory.EXECUTION,
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError


class MoveToTool(_SimActionTool):
    def __init__(self, world: WorldState) -> None:
        super().__init__(
            world,
            name="move_to",
            description="移动到小镇内某一地点。",
            parameters={
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "enum": list(LOCATIONS),
                        "description": "目标地点",
                    },
                    "reason": {"type": "string", "description": "此刻你的内心想法（第一人称口语，为什么去那儿）"},
                },
                "required": ["destination", "reason"],
            },
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        dest = str(arguments.get("destination", "")).strip()
        reason = str(arguments.get("reason", "")).strip()
        agent = self._world.agents.get(context.agent_id)
        if agent is None:
            return ToolResult(
                tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE
            )
        if dest not in LOCATIONS:
            return ToolResult(
                tool_call_id="",
                success=False,
                output=f"地点「{dest}」不存在，可选：{', '.join(LOCATIONS)}",
                effect=ToolEffect.CONTINUE,
            )
        old = agent.location
        async with self._world.mutation_lock():
            agent = self._world.agents[context.agent_id]
            agent.location = dest
            agent.position = position_for_location(dest)
            agent.activity = f"前往{dest}"
            line = f"tick{self._world.tick} {agent.name} 从{old}走到{dest}（{reason}）"
            self._world.event_log.append(line)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已到达{dest}。动机：{reason}",
            effect=ToolEffect.CONTINUE,
        )


class StayHereTool(_SimActionTool):
    def __init__(self, world: WorldState) -> None:
        super().__init__(
            world,
            name="stay_here",
            description="留在原地做一件事（工作、休息、观察等）。",
            parameters={
                "type": "object",
                "properties": {
                    "activity": {"type": "string", "description": "在此地做什么"},
                    "reason": {"type": "string", "description": "此刻你的内心想法（第一人称口语，为什么这么做）"},
                },
                "required": ["activity", "reason"],
            },
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        activity = str(arguments.get("activity", "")).strip()
        reason = str(arguments.get("reason", "")).strip()
        agent = self._world.agents.get(context.agent_id)
        if agent is None:
            return ToolResult(
                tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE
            )
        async with self._world.mutation_lock():
            agent = self._world.agents[context.agent_id]
            agent.activity = activity
            line = f"tick{self._world.tick} {agent.name} 在{agent.location}{activity}（{reason}）"
            self._world.event_log.append(line)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"留在{agent.location}，活动：{activity}。动机：{reason}",
            effect=ToolEffect.CONTINUE,
        )


class SpeakToTool(_SimActionTool):
    def __init__(self, world: WorldState) -> None:
        super().__init__(
            world,
            name="speak_to",
            description="对同地点的另一居民说一句话。",
            parameters={
                "type": "object",
                "properties": {
                    "target_name": {"type": "string", "description": "对方姓名"},
                    "message": {"type": "string", "description": "说的话（一两句）"},
                    "reason": {
                        "type": "string",
                        "description": "此刻你的内心想法（第一人称口语，为什么对 TA 说这些）",
                    },
                },
                "required": ["target_name", "message", "reason"],
            },
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        target_name = str(arguments.get("target_name", "")).strip()
        message = str(arguments.get("message", "")).strip()
        agent = self._world.agents.get(context.agent_id)
        if agent is None:
            return ToolResult(
                tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE
            )
        here = self._world.agents_at(agent.location, exclude=agent.agent_id)
        target = next((a for a in here if a.name == target_name), None)
        if target is None:
            names = ", ".join(a.name for a in here) or "无"
            return ToolResult(
                tool_call_id="",
                success=False,
                output=f"此地没有「{target_name}」，在场：{names}",
                effect=ToolEffect.CONTINUE,
            )
        async with self._world.mutation_lock():
            line = f"tick{self._world.tick} {agent.name}→{target.name}：「{message}」"
            self._world.event_log.append(line)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"你对{target.name}说：{message}",
            effect=ToolEffect.CONTINUE,
        )


class ProposeTradeTool(_SimActionTool):
    def __init__(self, world: WorldState) -> None:
        super().__init__(
            world,
            name="propose_trade",
            description="在市场向另一居民提议购买物品（对方需在场）。",
            parameters={
                "type": "object",
                "properties": {
                    "target_name": {"type": "string", "description": "卖家姓名"},
                    "item": {"type": "string", "description": "想买的物品"},
                    "quantity": {"type": "integer", "description": "数量", "minimum": 1},
                    "price": {"type": "number", "description": "出价（金币）"},
                    "reason": {"type": "string", "description": "交易动机"},
                },
                "required": ["target_name", "item", "quantity", "price", "reason"],
            },
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        target_name = str(arguments.get("target_name", "")).strip()
        item = str(arguments.get("item", "日用品")).strip() or "日用品"
        quantity = max(1, int(arguments.get("quantity", 1)))
        price = float(arguments.get("price", 10.0))
        reason = str(arguments.get("reason", "")).strip()
        agent = self._world.agents.get(context.agent_id)
        if agent is None:
            return ToolResult(
                tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE
            )
        if agent.location != "市场":
            return ToolResult(
                tool_call_id="",
                success=False,
                output="交易仅可在市场发起",
                effect=ToolEffect.CONTINUE,
            )
        here = self._world.agents_at(agent.location, exclude=agent.agent_id)
        target = next((a for a in here if a.name == target_name), None)
        if target is None:
            return ToolResult(
                tool_call_id="",
                success=False,
                output=f"市场没有「{target_name}」",
                effect=ToolEffect.CONTINUE,
            )
        bus = self._world.interaction_bus
        if bus is not None:
            bus.enqueue_kind(
                "trade",
                initiator_id=agent.agent_id,
                target_id=target.agent_id,
                params={
                    "item": item,
                    "quantity": quantity,
                    "price": price,
                    "buyer_is_initiator": True,
                    "reason": reason,
                },
            )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已向{target.name}提议：{price:.0f}币购买{item}×{quantity}（{reason}）",
            effect=ToolEffect.CONTINUE,
        )


class ProposeVoteTool(_SimActionTool):
    def __init__(self, world: WorldState) -> None:
        super().__init__(
            world,
            name="propose_vote",
            description="在镇政厅发起一项投票议题。",
            parameters={
                "type": "object",
                "properties": {
                    "motion": {"type": "string", "description": "投票议题（一句话）"},
                    "reason": {"type": "string", "description": "为何此时发起"},
                },
                "required": ["motion", "reason"],
            },
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        motion = str(arguments.get("motion", "")).strip()
        reason = str(arguments.get("reason", "")).strip()
        agent = self._world.agents.get(context.agent_id)
        if agent is None:
            return ToolResult(
                tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE
            )
        if agent.location != "镇政厅":
            return ToolResult(
                tool_call_id="",
                success=False,
                output="投票仅可在镇政厅发起",
                effect=ToolEffect.CONTINUE,
            )
        if not motion:
            return ToolResult(
                tool_call_id="", success=False, output="议题不能为空", effect=ToolEffect.CONTINUE
            )
        bus = self._world.interaction_bus
        if bus is not None:
            bus.enqueue_kind(
                "vote",
                initiator_id=agent.agent_id,
                params={"motion": motion, "reason": reason},
            )
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"已发起投票：{motion}（{reason}）",
            effect=ToolEffect.CONTINUE,
        )


def build_sim_tool_registry(world: WorldState) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        MoveToTool(world),
        StayHereTool(world),
        SpeakToTool(world),
        ProposeTradeTool(world),
        ProposeVoteTool(world),
    ):
        registry.register(tool)
    return registry
