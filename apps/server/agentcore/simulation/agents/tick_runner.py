"""Single SimAgent tick: one LLM round → one action (role-play, not a task turn).

Deliberately NOT ``react_loop``: a resident's tick is a single in-character
decision, not a multi-round task turn. Reusing the task engine leaked its
semantics into role-play — convergence steering injected「给出最终答案」reflection
prompts (agents replied with「## 最终答案」助手腔), multi-round ReAct let one tick
teleport through several locations, and ``deliverable_only`` discarded the very
in-character prose we want as the thought. This runs ONE round via
``run_llm_round`` and applies exactly the first action tool, keeping the streamed
prose verbatim as the agent's thought.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agentcore.config import settings
from agentcore.core.log_context import log_context, new_trace_id
from agentcore.core.types import new_id
from agentcore.evals.recording_sink import RecordingSink
from agentcore.llm.pricing import NANO_PER_USD, calculate_cost
from agentcore.llm.profiles import ProfileParams
from agentcore.llm.provider.protocol import LLMMessage, TokenUsage
from agentcore.runtime.engine.governance import resolve_openai_tool_defs
from agentcore.runtime.engine.round import LlmRoundFailure, run_llm_round
from agentcore.runtime.engine.tool_exec import execute_tools
from agentcore.simulation.agents.memory import format_tick_memories_for_perception
from agentcore.simulation.agents.models import (
    MotivationAssessment,
    MotivationSignals,
    SimPersona,
)
from agentcore.simulation.agents.tools import (
    MoveToTool,
    ProposeTradeTool,
    ProposeVoteTool,
    SpeakToTool,
    StayHereTool,
    build_sim_tool_registry,
)
from agentcore.simulation.scenarios.town.schedule import schedule_hint_for_persona
from agentcore.simulation.types import SimAgentAction
from agentcore.simulation.world.state import WorldState
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace

# Role-play tick = ONE LLM round, ONE action. max_rounds=1 keeps the engine's
# multi-round convergence steering (which injects「给出最终答案」reflection prompts
# that break character into助手腔) from ever firing — a resident thinks once and acts.
_SIM_PROFILE = ProfileParams(temperature=0.8, max_rounds=1, name="sim.town")


def _noop_emit(_delta: str) -> None:
    """Sink for streamed deltas — sim reads the final content, not the live stream."""


@dataclass
class AgentTickOutcome:
    action: SimAgentAction
    rounds: int
    latency_ms: int
    usage: dict[str, int]
    cost_usd: float
    error: str | None = None


def _build_messages(persona: SimPersona, perception: str, *, text_mode: bool) -> list[LLMMessage]:
    if text_mode:
        user_content = (
            f"{persona.system_prompt}\n\n"
            f"{perception}\n\n"
            "请根据你的人设与目标决定本 tick 行动。只输出一个 JSON 对象（不要 markdown），字段：\n"
            '{"action":"move_to|stay_here|speak_to",'
            '"destination":"地点(仅move_to)",'
            '"activity":"活动(仅stay_here)",'
            '"target_name":"姓名(仅speak_to)",'
            '"message":"对话(仅speak_to)",'
            '"reason":"动机",'
            '"thought":"一两句内心想法"}\n'
            "不要复读上一 tick 的原话；行动要具体、符合人设。"
        )
        return [LLMMessage(role="user", content=user_content)]
    user_tail = (
        f"{perception}\n\n"
        "请根据你的人设与目标决定本 tick 行动：先调用一个工具（move_to / stay_here / speak_to），"
        "再简短说明你的想法（不要重复工具参数原文）。"
    )
    return [
        LLMMessage(role="system", content=persona.system_prompt),
        LLMMessage(role="user", content=user_tail),
    ]


def _parse_action_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


async def _apply_parsed_action(
    world: WorldState, payload: dict, ctx: ToolContext
) -> tuple[str, str, str]:
    action = str(payload.get("action", "")).strip()
    args_json = json.dumps(payload, ensure_ascii=False)
    if action == "move_to":
        tool = MoveToTool(world)
        result = await tool.execute(
            {"destination": payload.get("destination", ""), "reason": payload.get("reason", "")},
            ctx,
        )
    elif action == "stay_here":
        tool = StayHereTool(world)
        result = await tool.execute(
            {"activity": payload.get("activity", ""), "reason": payload.get("reason", "")},
            ctx,
        )
    elif action == "speak_to":
        tool = SpeakToTool(world)
        result = await tool.execute(
            {"target_name": payload.get("target_name", ""), "message": payload.get("message", "")},
            ctx,
        )
    elif action == "propose_trade":
        tool = ProposeTradeTool(world)
        result = await tool.execute(
            {
                "target_name": payload.get("target_name", ""),
                "item": payload.get("item", "日用品"),
                "quantity": payload.get("quantity", 1),
                "price": payload.get("price", 10.0),
                "reason": payload.get("reason", ""),
            },
            ctx,
        )
    elif action == "propose_vote":
        tool = ProposeVoteTool(world)
        result = await tool.execute(
            {"motion": payload.get("motion", ""), "reason": payload.get("reason", "")},
            ctx,
        )
    else:
        return action or "unknown", "", f"unknown action: {action}"
    thought = str(payload.get("thought", "")).strip()
    return action, thought or result.output, args_json


def _thought_from_tool_args(args_raw: str) -> str:
    """Recover the in-character thought from a native tool call.

    DeepSeek (and most providers) return empty ``content`` when they emit a tool
    call, so ``content`` can't carry the resident's想法. The thought lives in the
    tool's ``reason`` arg (every sim action tool requires it); fall back to
    ``message`` so a ``speak_to`` still surfaces something if ``reason`` is absent.
    """
    if not args_raw:
        return ""
    try:
        args = json.loads(args_raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(args, dict):
        return ""
    return str(args.get("reason") or args.get("message") or "").strip()


def _action_from_tool(
    name: str, args_raw: str, thought: str, *, success: bool, detail: str
) -> SimAgentAction:
    tool_args: dict | None = None
    if args_raw:
        try:
            tool_args = json.loads(args_raw)
        except json.JSONDecodeError:
            tool_args = {"raw": args_raw}
    action_kind: Literal[
        "move_to", "stay_here", "speak_to", "propose_trade", "propose_vote", "idle", "error"
    ]
    if name in ("move_to", "stay_here", "speak_to", "propose_trade", "propose_vote"):
        action_kind = name  # type: ignore[assignment]
    elif success:
        action_kind = "idle"
    else:
        action_kind = "error"
    return SimAgentAction(
        agent_id="",
        action=action_kind,
        thought=thought,
        tool_name=name or None,
        tool_args=tool_args,
        success=success,
        detail=detail,
    )


async def run_agent_tick(
    *,
    world: WorldState,
    persona: SimPersona,
    llm,
    run_id: str,
    text_mode: bool = True,
    turn_model: str | None = None,
    workspace_root: Path | None = None,
) -> AgentTickOutcome:
    """Run perception → think → act for one agent on the current tick."""
    sink = RecordingSink()
    tools = ToolRegistry() if text_mode else build_sim_tool_registry(world)
    backend = ServerWorkspace(
        root=workspace_root or Path(tempfile.mkdtemp(prefix="sim-run-")),
        sandbox=SubprocessSandbox(),
    )
    ctx = ToolContext(
        execution_id=new_id(),
        run_id=run_id,
        agent_id=persona.agent_id,
        backend=backend,
        user_id="simulation",
    )
    agent_now = world.agents[persona.agent_id]
    perception = world.perceive(persona.agent_id)
    slot = schedule_hint_for_persona(persona, world.hour)
    perception = f"{perception}\n日程参考（可偏离）：{slot.location} · {slot.activity}"
    memory_block = format_tick_memories_for_perception(agent_now.tick_memories)
    if memory_block:
        perception = f"{perception}\n{memory_block}"
    motivation = MotivationAssessment.evaluate(
        persona,
        MotivationSignals(
            hour=world.hour,
            mood=agent_now.mood,
            money=agent_now.money,
            others_present=len(world.agents_at(agent_now.location, exclude=persona.agent_id)),
            at_home=agent_now.location == "住宅区",
            market_price_multiplier=world.modifiers.market_price_multiplier,
            storm_active=world.modifiers.storm_active,
            festival_active=world.modifiers.festival_active,
        ),
    )
    perception = f"{perception}\n{motivation.hint_line()}"
    messages = _build_messages(persona, perception, text_mode=text_mode)
    model = turn_model or settings.platform_model
    # text_mode → no tools (model emits a JSON action); native tools → offer the sim
    # action tools. Either way we run ONE round and apply exactly one action.
    tool_defs = None if text_mode else resolve_openai_tool_defs(tools, None, set())
    t0 = time.monotonic()
    with log_context(trace_id=new_trace_id(), user_id="simulation", agent=persona.agent_id):
        try:
            result = await run_llm_round(
                llm=llm,
                profile=_SIM_PROFILE,
                messages=messages,
                investigation_tools=frozenset(),
                tool_defs=tool_defs,
                active_model=model,
                emit_content=_noop_emit,
                emit_reasoning=_noop_emit,
                on_tool_progress=None,
                round_idx=0,
                run_id=run_id,
                raise_on_error=True,
            )
            if isinstance(result, LlmRoundFailure):
                raise RuntimeError(result.error_message or "LLM round failed")
            content = result.content or ""
            usage = result.usage or TokenUsage()
            # The agent's in-character prose IS its thought — kept verbatim (no
            # deliverable rollback that would discard it in favour of a later
            # "summary" round).
            thought = content
            action_name = ""
            args_json = ""
            success = True
            detail = ""
            if text_mode:
                payload = _parse_action_json(content)
                if payload:
                    action_name, thought, args_json = await _apply_parsed_action(
                        world, payload, ctx
                    )
                else:
                    success = False
                    detail = "failed to parse action JSON"
                    action_name = "error"
            elif result.tool_calls:
                # One tick = one action: apply exactly the FIRST tool the agent chose,
                # so a resident can't teleport through several locations in a single tick.
                first = result.tool_calls[0]
                _msgs, _terminal, attempts = await execute_tools(
                    [first], tools, ctx, sink, run_id=run_id
                )
                action_name = first.function.name
                args_json = first.function.arguments or ""
                # Native tool-calling returns empty content — the in-character thought
                # lives in the tool's ``reason`` arg. Recover it (fallback to any prose).
                thought = _thought_from_tool_args(args_json) or content
                if attempts and not attempts[0].success:
                    success = False
                    detail = (_msgs[0].content if _msgs else "") or "行动失败"
            else:
                success = False
                detail = "模型未选择任何行动工具"
                action_name = "idle"
            agent = world.agents[persona.agent_id]
            async with world.mutation_lock():
                agent.last_thought = thought
            cost = calculate_cost(model, usage, billing_mode="platform").total
            action = _action_from_tool(
                action_name, args_json, thought, success=success, detail=detail
            )
            action.agent_id = persona.agent_id
            return AgentTickOutcome(
                action=action,
                rounds=1,
                latency_ms=int((time.monotonic() - t0) * 1000),
                usage=usage.as_dict(),
                cost_usd=cost / NANO_PER_USD,
            )
        except Exception as e:
            action = SimAgentAction(
                agent_id=persona.agent_id,
                action="error",
                thought="",
                success=False,
                detail=str(e),
            )
            return AgentTickOutcome(
                action=action,
                rounds=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                usage={},
                cost_usd=0.0,
                error=str(e),
            )
