"""Per-agent tick memory — sliding window of one-line summaries (BE-12).

Anti-drift (WS-D): over long runs a naive "keep last N" window lets routine repetition
crowd out salient memories (reflections, interactions) and lets the agent's self-narrative
drift by re-reading near-identical lines every tick. Two guards address this without changing
the wire shape (``tick_memories`` stays ``list[str]``):

1. Salience-aware retention on trim — evict the lowest-salience *oldest* line, never the
   newest, so reflections/interactions survive a wall of routine ticks. Degrades to plain
   FIFO when every entry is equally routine.
2. Render-time compression — collapse consecutive identical actions into one ranged line
   for the prompt only, so the model is not reinforced by repetition. Storage is untouched.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.scenarios.town.schedule import schedule_hint_for_persona
from agentcore.simulation.types import SimAgentAction
from agentcore.simulation.world.state import WorldAgent, WorldState

MAX_TICK_MEMORIES = 10

# Salience tiers: higher survives longer under retention pressure.
_HIGH_SALIENCE_MARKERS = ("反思",)
_MID_SALIENCE_MARKERS = ("交谈", "→", "提议", "投票", "成交", "议题")

_TICK_LINE_RE = re.compile(r"^在 tick (\d+)，(.+)$")


def _salience(line: str) -> int:
    if any(marker in line for marker in _HIGH_SALIENCE_MARKERS):
        return 2
    if any(marker in line for marker in _MID_SALIENCE_MARKERS):
        return 1
    return 0


def append_tick_memory(agent: WorldAgent, summary: str) -> None:
    """Append a summary; when over the window evict the lowest-salience oldest entry.

    The newest entry is always retained. Ties are broken oldest-first, so an all-routine
    history behaves exactly like the previous ``[-N:]`` window.
    """
    memories = agent.tick_memories
    memories.append(summary)
    if len(memories) <= MAX_TICK_MEMORIES:
        return
    evictable = range(len(memories) - 1)  # protect the just-appended newest entry
    victim = min(evictable, key=lambda i: (_salience(memories[i]), i))
    del memories[victim]


def _compress_consecutive(memories: Sequence[str]) -> list[str]:
    """Collapse consecutive same-action tick lines into one ranged line (prompt only)."""
    out: list[str] = []
    index = 0
    total = len(memories)
    while index < total:
        match = _TICK_LINE_RE.match(memories[index])
        if match is None:
            out.append(memories[index])
            index += 1
            continue
        body = match.group(2)
        start_tick = match.group(1)
        end_tick = start_tick
        run = index + 1
        while run < total:
            next_match = _TICK_LINE_RE.match(memories[run])
            if next_match is None or next_match.group(2) != body:
                break
            end_tick = next_match.group(1)
            run += 1
        streak = run - index
        if streak == 1:
            out.append(memories[index])
        else:
            out.append(f"在 tick {start_tick}–{end_tick}，{body}（连续{streak}次）")
        index = run
    return out


def format_tick_memories_for_perception(memories: Sequence[str]) -> str:
    """Render stored summaries for injection into agent perception (compressed)."""
    if not memories:
        return ""
    lines = "\n".join(f"- {m}" for m in _compress_consecutive(memories))
    return f"【你的近期记忆】\n{lines}"


def _describe_action(agent: WorldAgent, action: SimAgentAction) -> str:
    args = action.tool_args or {}
    if action.action == "move_to":
        dest = str(args.get("destination", "")).strip() or agent.location
        return f"前往了{dest}"
    if action.action == "stay_here":
        activity = str(args.get("activity", "")).strip() or agent.activity
        return f"留在{agent.location}做{activity}"
    if action.action == "speak_to":
        target = str(args.get("target_name", "")).strip() or "某人"
        return f"与{target}交谈"
    if action.action == "error" or not action.success:
        return "尝试行动但失败了"
    return f"在{agent.location}{agent.activity}"


def _describe_encounter(world: WorldState, agent: WorldAgent) -> str:
    prefix = f"tick{world.tick}"
    relevant = [
        line
        for line in world.event_log
        if line.startswith(prefix) and agent.name in line
    ]
    if relevant:
        tail = relevant[-1].split(agent.name, 1)[-1].strip()
        return tail.lstrip("，").strip() or "镇上的公共事件"
    here = world.agents_at(agent.location, exclude=agent.agent_id)
    if here:
        names = "、".join(a.name for a in here)
        return f"同处此地的{names}"
    return "无特别事件"


def summarize_agent_tick(
    *,
    tick: int,
    agent: WorldAgent,
    action: SimAgentAction,
    encounter: str,
) -> str:
    """Fixed-format one-line summary: 在 tick N，你做了 X，遇到了 Y."""
    action_desc = _describe_action(agent, action)
    return f"在 tick {tick}，你{action_desc}，遇到了{encounter}"


def summarize_schedule_fallback(
    *,
    tick: int,
    location: str,
    activity: str,
) -> str:
    return f"在 tick {tick}，你按日程在{location}{activity}，遇到了无特别事件"


def apply_tick_memories(
    world: WorldState,
    outcomes: Sequence[object],
    skipped: Sequence[SimPersona],
) -> None:
    """Write one summary per agent at end of tick (after outcomes are known)."""
    tick = world.tick
    for outcome in outcomes:
        action = getattr(outcome, "action", None)
        if action is None:
            continue
        agent_id = action.agent_id
        agent = world.agents.get(agent_id)
        if agent is None:
            continue
        encounter = _describe_encounter(world, agent)
        summary = summarize_agent_tick(
            tick=tick, agent=agent, action=action, encounter=encounter
        )
        append_tick_memory(agent, summary)

    for persona in skipped:
        agent = world.agents.get(persona.agent_id)
        if agent is None:
            continue
        slot = schedule_hint_for_persona(persona, world.hour)
        summary = summarize_schedule_fallback(
            tick=tick, location=slot.location, activity=slot.activity
        )
        append_tick_memory(agent, summary)
