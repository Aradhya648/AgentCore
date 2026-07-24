"""Simulation data access (simulation_run / sim_tick / sim_agent / sim_event)."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.core.types import new_id
from agentcore.db.models.simulation import SimAgent, SimEvent, SimTick, SimulationRun
from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.observe.types import TickMetrics
from agentcore.simulation.types import SimAgentState, SimTickSnapshot, Vec3


class SimulationRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_run(
        self,
        *,
        user_id: str,
        scenario: str = "town",
        seed: int = 0,
        config: dict | None = None,
    ) -> SimulationRun:
        run = SimulationRun(
            id=new_id(),
            user_id=user_id,
            scenario=scenario,
            seed=seed,
            status="created",
            config=config or {},
            current_tick=0,
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return run

    async def get_run(self, run_id: str, *, user_id: str) -> SimulationRun | None:
        result = await self._session.execute(
            select(SimulationRun).where(
                SimulationRun.id == run_id,
                SimulationRun.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_run_status(self, run_id: str, *, status: str, current_tick: int) -> None:
        await self._session.execute(
            update(SimulationRun)
            .where(SimulationRun.id == run_id)
            .values(status=status, current_tick=current_tick)
        )
        await self._session.commit()

    async def update_run_config(self, run_id: str, config: dict) -> None:
        await self._session.execute(
            update(SimulationRun).where(SimulationRun.id == run_id).values(config=config)
        )
        await self._session.commit()

    async def merge_run_config(self, run_id: str, patch: dict) -> dict:
        run = await self._session.get(SimulationRun, run_id)
        if run is None:
            raise KeyError("run not found")
        merged = dict(run.config or {})
        merged.update(patch)
        await self._session.execute(
            update(SimulationRun).where(SimulationRun.id == run_id).values(config=merged)
        )
        await self._session.commit()
        return merged

    async def patch_agent_fields(
        self,
        run_id: str,
        agent_id: str,
        *,
        mood: float | None = None,
        goal: str | None = None,
        money: float | None = None,
    ) -> SimAgentState:
        row = await self._get_agent_row(run_id, agent_id)
        if row is None:
            raise KeyError("agent not found")
        if mood is not None:
            row.mood = mood
        if goal is not None:
            row.goal = goal
        if money is not None:
            extra = dict(row.state_extra or {})
            extra["money"] = money
            row.state_extra = extra
        await self._session.execute(
            update(SimAgent)
            .where(SimAgent.run_id == run_id, SimAgent.agent_id == agent_id)
            .values(
                mood=row.mood,
                goal=row.goal,
                state_extra=row.state_extra,
            )
        )
        await self._session.commit()
        return self.agent_state_from_row(row)

    async def _get_agent_row(self, run_id: str, agent_id: str) -> SimAgent | None:
        result = await self._session.execute(
            select(SimAgent).where(SimAgent.run_id == run_id, SimAgent.agent_id == agent_id)
        )
        return result.scalar_one_or_none()

    async def set_run_status(self, run_id: str, *, status: str) -> None:
        await self._session.execute(
            update(SimulationRun).where(SimulationRun.id == run_id).values(status=status)
        )
        await self._session.commit()

    async def add_agent(self, run_id: str, persona: SimPersona, state: SimAgentState) -> SimAgent:
        row = SimAgent(
            id=new_id(),
            run_id=run_id,
            agent_id=persona.agent_id,
            name=persona.name,
            role=persona.role,
            persona=persona.model_dump(),
            location=state.location,
            position=state.position.model_dump(),
            mood=state.mood,
            activity=state.activity,
            goal=state.goal,
            state_extra=self._state_extra_from(state),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def list_agents(self, run_id: str) -> list[SimAgent]:
        result = await self._session.execute(
            select(SimAgent).where(SimAgent.run_id == run_id).order_by(SimAgent.agent_id)
        )
        return list(result.scalars().all())

    async def update_agent_state(self, run_id: str, state: SimAgentState) -> None:
        await self._session.execute(
            update(SimAgent)
            .where(SimAgent.run_id == run_id, SimAgent.agent_id == state.agent_id)
            .values(
                location=state.location,
                position=state.position.model_dump(),
                mood=state.mood,
                activity=state.activity,
                goal=state.goal,
                state_extra=self._state_extra_from(state),
            )
        )
        await self._session.commit()

    async def bulk_update_agent_states(self, run_id: str, states: list[SimAgentState]) -> None:
        for state in states:
            await self._session.execute(
                update(SimAgent)
                .where(SimAgent.run_id == run_id, SimAgent.agent_id == state.agent_id)
                .values(
                    location=state.location,
                    position=state.position.model_dump(),
                    mood=state.mood,
                    activity=state.activity,
                    goal=state.goal,
                    state_extra=self._state_extra_from(state),
                )
            )
        await self._session.commit()

    async def write_tick(self, run_id: str, snapshot: SimTickSnapshot) -> SimTick:
        row = SimTick(
            id=new_id(),
            run_id=run_id,
            tick_number=snapshot.tick,
            hour=snapshot.hour,
            snapshot=snapshot.model_dump(),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def get_tick(self, run_id: str, tick_number: int) -> SimTick | None:
        result = await self._session.execute(
            select(SimTick).where(
                SimTick.run_id == run_id,
                SimTick.tick_number == tick_number,
            )
        )
        return result.scalar_one_or_none()

    async def append_event(
        self, run_id: str, *, tick_number: int, event_type: str, payload: dict
    ) -> SimEvent:
        row = SimEvent(
            id=new_id(),
            run_id=run_id,
            tick_number=tick_number,
            event_type=event_type,
            payload=payload,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return row

    async def list_events_for_tick(self, run_id: str, tick_number: int) -> list[SimEvent]:
        result = await self._session.execute(
            select(SimEvent)
            .where(SimEvent.run_id == run_id, SimEvent.tick_number == tick_number)
            .order_by(SimEvent.created_at)
        )
        return list(result.scalars().all())

    async def list_ticks_in_range(
        self, run_id: str, from_tick: int, to_tick: int
    ) -> list[SimTick]:
        result = await self._session.execute(
            select(SimTick)
            .where(
                SimTick.run_id == run_id,
                SimTick.tick_number >= from_tick,
                SimTick.tick_number <= to_tick,
            )
            .order_by(SimTick.tick_number)
        )
        return list(result.scalars().all())

    async def list_events_in_range(
        self, run_id: str, from_tick: int, to_tick: int
    ) -> list[SimEvent]:
        result = await self._session.execute(
            select(SimEvent)
            .where(
                SimEvent.run_id == run_id,
                SimEvent.tick_number >= from_tick,
                SimEvent.tick_number <= to_tick,
            )
            .order_by(SimEvent.tick_number, SimEvent.created_at)
        )
        return list(result.scalars().all())

    async def list_tick_metrics(self, run_id: str) -> list[TickMetrics]:
        result = await self._session.execute(
            select(SimTick)
            .where(SimTick.run_id == run_id)
            .order_by(SimTick.tick_number)
        )
        metrics: list[TickMetrics] = []
        for row in result.scalars().all():
            snap = row.snapshot or {}
            raw = snap.get("metrics")
            if raw:
                metrics.append(TickMetrics.model_validate(raw))
        return metrics

    @staticmethod
    def _state_extra_from(state: SimAgentState) -> dict:
        return {
            "last_thought": state.last_thought,
            "relationships": dict(state.relationships),
            "tick_memories": list(state.tick_memories),
            "money": state.money,
            "inventory": dict(state.inventory),
        }

    @staticmethod
    def agent_state_from_row(row: SimAgent) -> SimAgentState:
        pos = row.position or {}
        extra = row.state_extra or {}
        raw_rel = extra.get("relationships") or {}
        relationships = {str(k): float(v) for k, v in raw_rel.items()}
        raw_memories = extra.get("tick_memories") or []
        tick_memories = [str(m) for m in raw_memories]
        raw_inventory = extra.get("inventory") or {"粮食": 3, "日用品": 2}
        inventory = {str(k): int(v) for k, v in raw_inventory.items()}
        return SimAgentState(
            agent_id=row.agent_id,
            name=row.name,
            role=row.role,
            location=row.location,
            position=Vec3(**pos) if pos else Vec3(),
            activity=row.activity,
            mood=row.mood,
            goal=row.goal,
            last_thought=str(extra.get("last_thought", "")),
            relationships=relationships,
            tick_memories=tick_memories,
            money=float(extra.get("money", 100.0)),
            inventory=inventory,
        )
