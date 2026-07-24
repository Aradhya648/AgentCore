"""M1 closed-loop tests: create run → 1 agent → 1 tick → events + tick readback."""

from __future__ import annotations

import json

import pytest

from agentcore.evals.spikes.sim.mock_provider import ScriptedProvider, content_chunk
from agentcore.llm.provider.protocol import LLMChunk, ToolCallDelta
from agentcore.runtime.events import EventType
from agentcore.simulation.agents.tick_runner import run_agent_tick
from agentcore.simulation.scenarios.town.config import LIN_PERSONA, seed_town_world
from agentcore.simulation.types import SimTickSnapshot
from agentcore.simulation.world.engine import WorldEngine


def _text_json_provider(destination: str = "市场") -> ScriptedProvider:
    payload = json.dumps(
        {
            "action": "move_to",
            "destination": destination,
            "reason": "去进面粉",
            "thought": "得赶紧去市场进原料。",
        },
        ensure_ascii=False,
    )
    return ScriptedProvider([[content_chunk(payload)]])


@pytest.mark.asyncio
async def test_single_agent_tick_text_json_moves_agent():
    world = seed_town_world()
    engine = WorldEngine(world=world)
    await engine.advance()
    outcome = await run_agent_tick(
        world=world,
        persona=LIN_PERSONA,
        llm=_text_json_provider(),
        run_id="test-run",
        text_mode=True,
    )
    assert outcome.error is None
    assert outcome.action.action == "move_to"
    assert world.agents["lin"].location == "市场"
    assert world.agents["lin"].position.x == 36


@pytest.mark.asyncio
async def test_world_engine_snapshot_roundtrip():
    world = seed_town_world()
    engine = WorldEngine(world=world)
    snap = await engine.advance()
    assert snap.tick == 1
    assert snap.hour == 9
    world2 = seed_town_world()
    world2.load_snapshot(snap)
    assert world2.tick == 1
    assert "lin" in world2.agents


def test_sim_event_types_registered():
    assert EventType.SIM_TICK_STARTED.value == "sim.tick_started"
    assert EventType.SIM_TICK_ENDED.value == "sim.tick_ended"
    assert EventType.SIM_AGENT_ACTION.value == "sim.agent_action"
    assert EventType.SIM_AGENT_STATE.value == "sim.agent_state"
    assert EventType.SIM_WORLD_EVENT.value == "sim.world_event"


def test_tick_snapshot_schema():
    snap = SimTickSnapshot(tick=1, hour=9, agents={}, event_log=[])
    assert snap.model_dump()["tick"] == 1


def _native_two_moves_provider() -> ScriptedProvider:
    """Native-tools round: empty content (as real providers emit) + TWO move_to in ONE round.

    Real DeepSeek/OpenAI native tool-calling returns empty ``content`` next to the
    tool_calls, so the thought must be lifted from the tool's ``reason`` arg — this
    provider emits empty content to reproduce that (the earlier non-empty content
    masked the blank-thought bug).
    """
    return ScriptedProvider(
        [
            [
                content_chunk(""),
                LLMChunk(
                    delta_tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="c1",
                            function_name="move_to",
                            arguments_delta='{"destination": "市场", "reason": "看行情"}',
                        )
                    ]
                ),
                LLMChunk(
                    delta_tool_calls=[
                        ToolCallDelta(
                            index=1,
                            id="c2",
                            function_name="move_to",
                            arguments_delta='{"destination": "工坊", "reason": "顺路"}',
                        )
                    ]
                ),
            ]
        ]
    )


@pytest.mark.asyncio
async def test_native_tools_single_action_thought_from_reason():
    """A role-play tick is ONE round → ONE action; thought is lifted from the tool reason.

    Guards two invariants of the tick_runner decouple from react_loop:
    - single action / single round: even when the model emits two tool calls, only the
      FIRST applies (林小梅 lands at 市场, never teleports to 工坊); rounds == 1.
    - thought recovery: native tool-calling returns empty content, so the in-character
      想法 must come from the tool's ``reason`` arg. Regression guard for the bug where
      thought=content left every native-mode thought blank.
    """
    world = seed_town_world()
    world.tick = 1
    outcome = await run_agent_tick(
        world=world,
        persona=LIN_PERSONA,
        llm=_native_two_moves_provider(),
        run_id="test-run",
        text_mode=False,
    )
    assert outcome.error is None
    assert outcome.action.action == "move_to"
    assert world.agents["lin"].location == "市场"  # first action only, not 工坊
    assert outcome.action.thought == "看行情"  # from tool reason, since content is empty
    assert world.agents["lin"].last_thought == "看行情"
    assert outcome.rounds == 1  # single round
