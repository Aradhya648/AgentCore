"""Low-frequency SimAgent reflection loop (BE-24)."""

from __future__ import annotations

from collections.abc import Sequence

from agentcore.llm.provider.protocol import LLMProvider
from agentcore.simulation.agents.memory import append_tick_memory
from agentcore.simulation.agents.models import (
    MotivationAssessment,
    MotivationSignals,
    SimPersona,
)
from agentcore.simulation.interaction.llm_helpers import sim_complete_json
from agentcore.simulation.world.state import WorldAgent

REFLECTION_INTERVAL_TICKS = 12

# Goal anti-drift guard bounds: reject degenerate/near-duplicate rewrites, cap runaway length.
_MIN_GOAL_LEN = 4
_MAX_GOAL_LEN = 60


def should_reflect(tick: int, *, interval: int = REFLECTION_INTERVAL_TICKS) -> bool:
    return tick > 0 and tick % interval == 0


def anchor_goal(persona: SimPersona, current_goal: str, proposed: str | None) -> str | None:
    """Accept a reflected goal only if it is a meaningful, non-trivial change.

    Anti-drift: a reflection that returns an empty, too-short, or unchanged goal must not
    overwrite the agent's standing goal (which would erode the persona over many ticks).
    Returns the accepted goal (length-capped) or ``None`` to keep the current one.
    """
    text = (proposed or "").strip()
    if len(text) < _MIN_GOAL_LEN:
        return None
    if text == (current_goal or "").strip():
        return None
    return text[:_MAX_GOAL_LEN]


async def reflect_agent(
    *,
    persona: SimPersona,
    agent: WorldAgent,
    tick: int,
    llm: LLMProvider,
    model: str,
) -> tuple[str, str | None]:
    """LLM reflection: summarize recent behavior and optionally adjust goal.

    Returns ``(memory_summary, new_goal_or_none)``.
    """
    memories = "\n".join(f"- {m}" for m in agent.tick_memories[-6:]) or "（尚无记忆）"
    motivation = MotivationAssessment.evaluate(
        persona,
        MotivationSignals(hour=(8 + tick) % 24, mood=agent.mood, money=agent.money),
    )
    core_goals = "；".join(persona.effective_goals()) or persona.goal
    system = (
        f"{persona.system_prompt}\n"
        "请对近期行为做低频反思。目标微调必须与你的身份和长期目标一致，只在确有必要时"
        "小幅调整，不要凭空换成无关目标。只输出 JSON："
        '{"summary": "一两句总结近期行为与感受", '
        '"goal_adjustment": "可选的新目标（若无需调整则空字符串）", '
        '"priority_note": "可选的目标优先级说明"}'
    )
    user = (
        f"当前 tick {tick}，你在 {agent.location}，心情 {agent.mood:+.1f}。\n"
        f"你的长期目标：{core_goals}\n"
        f"当前目标：{agent.goal}\n"
        f"内在驱动：主导「{motivation.dominant_drive}」（{'；'.join(motivation.rationale[:2])}）\n"
        f"近期记忆：\n{memories}\n"
        "请反思并决定是否微调目标。"
    )
    payload, raw = await sim_complete_json(
        llm, model=model, system=system, user=user, temperature=0.6
    )
    if payload is None:
        summary = (raw or "本周期无特别反思。").strip()[:200]
        return f"反思 tick{tick}：{summary}", None

    summary = str(payload.get("summary", "")).strip() or "本周期行为平稳。"
    goal_adj = anchor_goal(persona, agent.goal, payload.get("goal_adjustment"))
    priority = str(payload.get("priority_note", "")).strip()
    memory_line = f"反思 tick{tick}：{summary}"
    if priority:
        memory_line = f"{memory_line}（{priority}）"
    return memory_line, goal_adj


async def apply_reflections(
    *,
    tick: int,
    agents: Sequence[tuple[SimPersona, WorldAgent]],
    llm: LLMProvider,
    model: str,
) -> list[str]:
    """Run reflection for all agents when the interval matches."""
    if not should_reflect(tick):
        return []
    notes: list[str] = []
    for persona, agent in agents:
        memory_line, new_goal = await reflect_agent(
            persona=persona, agent=agent, tick=tick, llm=llm, model=model
        )
        append_tick_memory(agent, memory_line)
        if new_goal:
            agent.goal = new_goal
            notes.append(f"{agent.name} 调整目标：{new_goal}")
    return notes
