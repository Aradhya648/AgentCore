"""Batch concurrent SimAgent tick execution (BE-08)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.agents.tick_runner import AgentTickOutcome, run_agent_tick
from agentcore.simulation.types import SimAgentAction
from agentcore.simulation.world.state import WorldState

OnAgentTickDone = Callable[[SimPersona, AgentTickOutcome], Awaitable[None]]


@dataclass(frozen=True)
class TickBatchOptions:
    max_parallel: int = 6
    timeout_seconds: float = 120.0


@dataclass
class TickBatchResult:
    outcomes: list[AgentTickOutcome]
    succeeded: int
    failed: int


def _timeout_outcome(persona: SimPersona, *, timeout_seconds: float) -> AgentTickOutcome:
    return AgentTickOutcome(
        action=SimAgentAction(
            agent_id=persona.agent_id,
            action="error",
            thought="",
            success=False,
            detail=f"agent tick timed out after {timeout_seconds:.0f}s",
        ),
        rounds=0,
        latency_ms=int(timeout_seconds * 1000),
        usage={},
        cost_usd=0.0,
        error=f"timeout after {timeout_seconds:.0f}s",
    )


async def run_agent_ticks_batch(
    *,
    world: WorldState,
    personas: Sequence[SimPersona],
    llm,
    run_id: str,
    text_mode: bool,
    turn_model: str | None = None,
    options: TickBatchOptions | None = None,
    on_agent_done: OnAgentTickDone | None = None,
) -> TickBatchResult:
    """Run one tick decision for each persona with bounded concurrency.

    Uses ``asyncio.gather`` + ``Semaphore``. Individual agent failures and timeouts
    are isolated — other agents continue to completion.
    """
    opts = options or TickBatchOptions()
    sem = asyncio.Semaphore(opts.max_parallel)
    outcomes: list[AgentTickOutcome] = []

    async def _one(persona: SimPersona) -> None:
        async with sem:
            try:
                outcome = await asyncio.wait_for(
                    run_agent_tick(
                        world=world,
                        persona=persona,
                        llm=llm,
                        run_id=run_id,
                        text_mode=text_mode,
                        turn_model=turn_model,
                    ),
                    timeout=opts.timeout_seconds,
                )
            except TimeoutError:
                outcome = _timeout_outcome(persona, timeout_seconds=opts.timeout_seconds)
            except Exception as exc:
                outcome = AgentTickOutcome(
                    action=SimAgentAction(
                        agent_id=persona.agent_id,
                        action="error",
                        thought="",
                        success=False,
                        detail=str(exc),
                    ),
                    rounds=0,
                    latency_ms=0,
                    usage={},
                    cost_usd=0.0,
                    error=str(exc),
                )
            outcomes.append(outcome)
            if on_agent_done is not None:
                await on_agent_done(persona, outcome)

    await asyncio.gather(*[_one(p) for p in personas])
    succeeded = sum(1 for o in outcomes if o.error is None)
    return TickBatchResult(
        outcomes=outcomes,
        succeeded=succeeded,
        failed=len(outcomes) - succeeded,
    )
