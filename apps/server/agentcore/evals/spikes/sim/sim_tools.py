"""SimAgent action tools — mutate in-memory world, no filesystem side effects."""

from __future__ import annotations

from typing import Any

from agentcore.core.types import ToolCategory, ToolEffect
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registry import ToolRegistry

from .world import LOCATIONS, WorldState


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
            return ToolResult(tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE)
        if dest not in LOCATIONS:
            return ToolResult(
                tool_call_id="",
                success=False,
                output=f"地点「{dest}」不存在，可选：{', '.join(LOCATIONS)}",
                effect=ToolEffect.CONTINUE,
            )
        old = agent.location
        agent.location = dest
        agent.activity = f"前往{dest}"
        line = f"tick{self._world.tick} {agent.name} 从{old}走到{dest}（{reason}）"
        self._world.record(line)
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
            return ToolResult(tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE)
        agent.activity = activity
        line = f"tick{self._world.tick} {agent.name} 在{agent.location}{activity}（{reason}）"
        self._world.record(line)
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
            return ToolResult(tool_call_id="", success=False, output="未知居民", effect=ToolEffect.CONTINUE)
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
        line = f"tick{self._world.tick} {agent.name}→{target.name}：「{message}」"
        self._world.record(line)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=f"你对{target.name}说：{message}",
            effect=ToolEffect.CONTINUE,
        )


def build_sim_tool_registry(world: WorldState) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (MoveToTool(world), StayHereTool(world), SpeakToTool(world)):
        registry.register(tool)
    return registry
