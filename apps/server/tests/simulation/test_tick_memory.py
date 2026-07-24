"""Unit tests for tick memory (BE-12)."""

from __future__ import annotations

import json

import pytest

from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.simulation.agents import tick_runner
from agentcore.simulation.agents.memory import (
    MAX_TICK_MEMORIES,
    append_tick_memory,
    apply_tick_memories,
    format_tick_memories_for_perception,
    summarize_agent_tick,
)
from agentcore.simulation.agents.tick_runner import AgentTickOutcome, run_agent_tick
from agentcore.simulation.scenarios.town.config import LIN_PERSONA, seed_town_world
from agentcore.simulation.types import SimAgentAction, SimAgentState, Vec3
from agentcore.simulation.world.engine import WorldEngine
from agentcore.simulation.world.state import WorldAgent


def test_append_tick_memory_trims_to_window():
    agent = WorldAgent(agent_id="a", name="A", role="r")
    for i in range(MAX_TICK_MEMORIES + 3):
        append_tick_memory(agent, f"mem-{i}")
    assert len(agent.tick_memories) == MAX_TICK_MEMORIES
    assert agent.tick_memories[0] == "mem-3"
    assert agent.tick_memories[-1] == f"mem-{MAX_TICK_MEMORIES + 2}"


def test_append_protects_high_salience_reflection_from_routine_flood():
    agent = WorldAgent(agent_id="a", name="A", role="r")
    append_tick_memory(agent, "反思 tick12：我要更用心经营面包店")
    for i in range(MAX_TICK_MEMORIES + 5):
        append_tick_memory(agent, f"在 tick {i}，你留在广场做闲逛，遇到了无特别事件")
    assert len(agent.tick_memories) == MAX_TICK_MEMORIES
    # The salient reflection survives even though it is the oldest entry.
    assert any(m.startswith("反思") for m in agent.tick_memories)


def test_format_compresses_consecutive_identical_actions():
    memories = [
        "在 tick 1，你留在面包店做烘焙，遇到了无特别事件",
        "在 tick 2，你留在面包店做烘焙，遇到了无特别事件",
        "在 tick 3，你留在面包店做烘焙，遇到了无特别事件",
        "在 tick 4，你前往了市场，遇到了无特别事件",
    ]
    block = format_tick_memories_for_perception(memories)
    assert "在 tick 1–3，你留在面包店做烘焙，遇到了无特别事件（连续3次）" in block
    assert "在 tick 4，你前往了市场，遇到了无特别事件" in block


def test_format_keeps_distinct_actions_uncompressed():
    memories = [
        "在 tick 1，你前往了市场，遇到了无特别事件",
        "在 tick 2，你留在市场做买卖，遇到了无特别事件",
    ]
    block = format_tick_memories_for_perception(memories)
    assert "连续" not in block


def test_format_tick_memories_for_perception_empty():
    assert format_tick_memories_for_perception([]) == ""


def test_format_tick_memories_for_perception_renders_block():
    block = format_tick_memories_for_perception(["在 tick 1，你留在广场做闲逛，遇到了无特别事件"])
    assert "【你的近期记忆】" in block
    assert "在 tick 1" in block


def test_summarize_agent_tick_fixed_format():
    agent = WorldAgent(agent_id="lin", name="林晓", role="面包师", location="面包店")
    outcome = AgentTickOutcome(
        action=SimAgentAction(
            agent_id="lin",
            action="stay_here",
            tool_args={"activity": "烘焙"},
            success=True,
        ),
        rounds=1,
        latency_ms=1,
        usage={},
        cost_usd=0.0,
    )
    summary = summarize_agent_tick(
        tick=2, agent=agent, action=outcome.action, encounter="同处此地的张三"
    )
    assert summary == "在 tick 2，你留在面包店做烘焙，遇到了同处此地的张三"


def test_apply_tick_memories_writes_per_agent():
    world = seed_town_world()
    world.tick = 1
    outcome = AgentTickOutcome(
        action=SimAgentAction(
            agent_id="lin",
            action="stay_here",
            tool_args={"activity": "烘焙"},
            success=True,
        ),
        rounds=1,
        latency_ms=1,
        usage={},
        cost_usd=0.0,
    )
    apply_tick_memories(world, [outcome], [])
    assert len(world.agents["lin"].tick_memories) == 1
    assert world.agents["lin"].tick_memories[0].startswith("在 tick 1，")


def test_state_roundtrip_preserves_tick_memories():
    state = SimAgentState(
        agent_id="lin",
        name="林晓",
        role="面包师",
        location="面包店",
        position=Vec3(),
        tick_memories=["在 tick 1，你留在面包店做烘焙，遇到了无特别事件"],
    )
    agent = WorldAgent.from_state(state)
    restored = agent.to_state()
    assert restored.tick_memories == state.tick_memories


@pytest.mark.asyncio
async def test_run_agent_tick_injects_memories_into_prompt():
    world = seed_town_world()
    world.agents["lin"].tick_memories = [
        "在 tick 1，你前往了市场，遇到了无特别事件"
    ]
    engine = WorldEngine(world=world)
    await engine.advance()

    captured: list[str] = []
    real_build = tick_runner._build_messages

    def _capture_build(persona, perception, *, text_mode):
        captured.append(perception)
        return real_build(persona, perception, text_mode=text_mode)

    payload = json.dumps(
        {"action": "stay_here", "activity": "烘焙", "reason": "x", "thought": "ok"},
        ensure_ascii=False,
    )
    provider = ScriptedProvider([[content_chunk(payload)]])

    from unittest.mock import patch

    with patch(
        "agentcore.simulation.agents.tick_runner._build_messages",
        side_effect=_capture_build,
    ):
        await run_agent_tick(
            world=world,
            persona=LIN_PERSONA,
            llm=provider,
            run_id="mem-test",
            text_mode=True,
        )

    assert captured
    assert "【你的近期记忆】" in captured[0]
    assert "在 tick 1，你前往了市场" in captured[0]
