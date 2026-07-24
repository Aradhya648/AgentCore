"""InteractionBus unit tests (M3)."""

from __future__ import annotations

import json

import pytest

from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.simulation.agents.tick_runner import AgentTickOutcome
from agentcore.simulation.interaction.bus import InteractionBus, InteractionTickContext
from agentcore.simulation.scenarios.town.config import LIN_PERSONA, ZHAO_PERSONA, seed_town_world
from agentcore.simulation.types import SimAgentAction


def _accept_json(**fields: object) -> ScriptedProvider:
    payload = json.dumps(fields, ensure_ascii=False)
    return ScriptedProvider([[content_chunk(payload)]])


@pytest.mark.asyncio
async def test_bus_conversation_from_speak_to_outcome():
    world = seed_town_world()
    world.agents["zhao"].location = world.agents["lin"].location
    bus = InteractionBus()
    outcome = AgentTickOutcome(
        action=SimAgentAction(
            agent_id="lin",
            action="speak_to",
            success=True,
            tool_args={"target_name": "赵老板", "message": "今天面包不错"},
        ),
        rounds=1,
        latency_ms=1,
        usage={},
        cost_usd=0.0,
    )
    bus.collect_from_outcomes(world, [outcome])
    assert bus.pending_count == 1

    llm = ScriptedProvider(
        [
            [content_chunk(json.dumps({"accept": True, "reason": "可以聊"}, ensure_ascii=False))],
            [content_chunk("你好呀")],
            [content_chunk("最近生意怎样？")],
            [content_chunk("还行，慢慢来吧")],
        ]
    )
    results = await bus.process_tick(
        InteractionTickContext(
            world=world,
            personas=[LIN_PERSONA, ZHAO_PERSONA],
            llm=llm,
            model="mock",
            run_id="test",
            tick=world.tick,
        )
    )
    assert len(results) == 1
    assert results[0].kind == "conversation"
    assert results[0].status in ("completed", "rejected")


def test_sim_interaction_event_type_registered():
    from agentcore.runtime.events import EventType

    assert EventType.SIM_INTERACTION.value == "sim.interaction"
