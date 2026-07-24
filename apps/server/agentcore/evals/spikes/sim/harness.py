"""Single-round SimAgent tick harness (SPIKE-03 core).

Evaluation-side twin of the product decision path
(``simulation/agents/tick_runner.py``): one LLM round → one action, kept in
lockstep so SPIKE runs reflect real product behaviour. Deliberately NOT
``react_loop`` — that task engine's multi-round / convergence / deliverable
semantics corrupt role-play (助手腔「最终答案」, single-tick teleporting, discarded
in-character prose). TODO(tech-debt): this duplicates tick_runner over a separate
WorldState/Persona model; the two should converge onto one runtime.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from agentcore.config import settings
from agentcore.core.log_context import log_context, new_trace_id
from agentcore.core.types import new_id
from agentcore.evals.recording_sink import RecordingSink
from agentcore.llm.factory import build_provider
from agentcore.llm.pricing import NANO_PER_USD, calculate_cost
from agentcore.llm.profiles import ProfileParams
from agentcore.llm.provider.protocol import LLMMessage, TokenUsage
from agentcore.runtime.engine.governance import resolve_openai_tool_defs
from agentcore.runtime.engine.round import LlmRoundFailure, run_llm_round
from agentcore.runtime.engine.tool_exec import execute_tools
from agentcore.simulation.llm import build_sim_provider
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registry import ToolRegistry
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace

from .personas import Persona, persona_by_id
from .sim_tools import MoveToTool, SpeakToTool, StayHereTool, build_sim_tool_registry
from .world import WorldState

# Lockstep with product tick_runner: a role-play tick is ONE round → ONE action.
# max_rounds=1 stops the task engine's multi-round convergence steering (which
# injects「给出最终答案」reflection prompts that break character into助手腔).
_SIM_PROFILE = ProfileParams(temperature=0.8, max_rounds=1, name="sim.spike")


def _noop_emit(_delta: str) -> None:
    """Streamed deltas are ignored — the spike reads the final content."""


@dataclass
class TickResult:
    agent_id: str
    tick: int
    content: str
    tool_calls: list[tuple[str, str]]
    rounds: int
    latency_ms: int
    usage: dict[str, int]
    cost_usd: float
    error: str | None = None


@dataclass
class TranscriptLine:
    tick: int
    hour: int
    agent_id: str
    agent_name: str
    location: str
    activity: str
    content: str
    tools: list[tuple[str, str]] = field(default_factory=list)


def _sim_profile() -> ProfileParams:
    return _SIM_PROFILE


def _build_messages(persona: Persona, perception: str, *, text_mode: bool = False) -> list[LLMMessage]:
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


def _thought_from_tool_args(args_raw: str) -> str:
    """Recover the in-character thought from a native tool call.

    Native tool-calling returns empty ``content``; the resident's想法 lives in the
    tool's ``reason`` arg (fallback to ``message`` for speak_to). Lockstep with
    product ``tick_runner._thought_from_tool_args``.
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


async def _apply_parsed_action(world: WorldState, persona: Persona, payload: dict, ctx: ToolContext) -> tuple[str, str]:
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
    else:
        return "", f"unknown action: {action}"
    thought = str(payload.get("thought", "")).strip()
    return thought or result.output, args_json


async def run_agent_tick(
    *,
    world: WorldState,
    persona: Persona,
    llm,
    workspace_root: Path | None = None,
    text_mode: bool | None = None,
    turn_model: str | None = None,
) -> TickResult:
    """Run one SimAgent tick via react_loop — no conversation / turn / journal binding."""
    sink = RecordingSink()
    effective_text_mode = text_mode if text_mode is not None else False
    backend = ServerWorkspace(
        root=workspace_root or Path(tempfile.mkdtemp(prefix="sim-spike-")),
        sandbox=SubprocessSandbox(),
    )
    ctx = ToolContext(
        execution_id=new_id(),
        run_id=new_id(),
        agent_id=persona.agent_id,
        backend=backend,
        user_id="sim-spike",
    )
    perception = world.perceive(persona.agent_id)
    messages = _build_messages(persona, perception, text_mode=effective_text_mode)
    tools = ToolRegistry() if effective_text_mode else build_sim_tool_registry(world)
    model = turn_model or settings.platform_model
    tool_defs = None if effective_text_mode else resolve_openai_tool_defs(tools, None, set())
    t0 = time.monotonic()
    with log_context(trace_id=new_trace_id(), user_id="sim-spike", agent=persona.agent_id):
        try:
            result = await run_llm_round(
                llm=llm,
                profile=_sim_profile(),
                messages=messages,
                investigation_tools=frozenset(),
                tool_defs=tool_defs,
                active_model=model,
                emit_content=_noop_emit,
                emit_reasoning=_noop_emit,
                on_tool_progress=None,
                round_idx=0,
                run_id=ctx.run_id,
                raise_on_error=True,
            )
            if isinstance(result, LlmRoundFailure):
                raise RuntimeError(result.error_message or "LLM round failed")
            content = result.content or ""
            usage = result.usage or TokenUsage()
            tool_calls: list[tuple[str, str]] = []
            if effective_text_mode:
                payload = _parse_action_json(content)
                if payload:
                    thought, args_json = await _apply_parsed_action(world, persona, payload, ctx)
                    content = thought
                    tool_calls = [(str(payload.get("action", "?")), args_json)]
            elif result.tool_calls:
                # One tick = one action: apply exactly the FIRST tool the agent chose.
                first = result.tool_calls[0]
                await execute_tools([first], tools, ctx, sink, run_id=ctx.run_id)
                args_json = first.function.arguments or ""
                tool_calls = [(first.function.name, args_json)]
                # Native tool-calling returns empty content — the in-character thought
                # lives in the tool's ``reason`` arg. Recover it (fallback to any prose).
                content = _thought_from_tool_args(args_json) or content
            cost = calculate_cost(model, usage, billing_mode="platform").total
            agent = world.agents[persona.agent_id]
            agent.last_thought = content or ""
            return TickResult(
                agent_id=persona.agent_id,
                tick=world.tick,
                content=content or "",
                tool_calls=tool_calls,
                rounds=1,
                latency_ms=int((time.monotonic() - t0) * 1000),
                usage=usage.as_dict(),
                cost_usd=cost / NANO_PER_USD,
            )
        except Exception as e:
            return TickResult(
                agent_id=persona.agent_id,
                tick=world.tick,
                content="",
                tool_calls=list(sink.tool_calls),
                rounds=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                usage={},
                cost_usd=0.0,
                error=str(e),
            )


def tick_to_transcript(world: WorldState, persona: Persona, result: TickResult) -> TranscriptLine:
    agent = world.agents[persona.agent_id]
    return TranscriptLine(
        tick=world.tick,
        hour=world.hour,
        agent_id=persona.agent_id,
        agent_name=persona.name,
        location=agent.location,
        activity=agent.activity,
        content=result.content,
        tools=list(result.tool_calls),
    )


def format_transcript_line(line: TranscriptLine) -> str:
    tools = ", ".join(f"{n}({a})" for n, a in line.tools) if line.tools else "（无工具）"
    return (
        f"[tick {line.tick:02d} {line.hour:02d}:00] {line.agent_name} @ {line.location} "
        f"| {line.activity}\n"
        f"  工具: {tools}\n"
        f"  想法: {line.content or '（空）'}"
    )


async def run_spike03_mock() -> TickResult:
    """SPIKE-03: single agent, mock LLM, one tick."""
    from .mock_provider import mock_move_then_summarize
    from .personas import seed_world

    world = seed_world()
    persona = persona_by_id("lin")
    provider = mock_move_then_summarize()
    return await run_agent_tick(world=world, persona=persona, llm=provider)


def build_real_llm():
    """Sync stub — prefer :func:`build_real_llm_async` for DeepSeek resolution."""
    return build_provider()


async def build_real_llm_async(session, user_id: str | None = None):
    return await build_sim_provider(session, user_id)
