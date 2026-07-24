"""Interaction request routing and tick-scoped execution (BE-15)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentcore.core.types import new_id
from agentcore.llm.provider.protocol import LLMProvider
from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.interaction.conversation import ConversationContext, run_conversation
from agentcore.simulation.interaction.models import (
    InteractionKind,
    InteractionRequest,
    InteractionResult,
)
from agentcore.simulation.interaction.trade import TradeContext, run_trade
from agentcore.simulation.interaction.vote import VoteContext, run_vote
from agentcore.simulation.show.heart_pick import HeartPickContext, run_heart_pick
from agentcore.simulation.world.state import WorldState

if TYPE_CHECKING:
    from agentcore.simulation.agents.tick_runner import AgentTickOutcome
    from agentcore.simulation.show.models import ShowSeasonState

OnInteractionDone = Callable[[InteractionResult], Awaitable[None]]


@dataclass
class InteractionTickContext:
    world: WorldState
    personas: Sequence[SimPersona]
    llm: LLMProvider
    model: str
    run_id: str
    tick: int
    on_result: OnInteractionDone | None = None
    show_season: ShowSeasonState | None = None
    show_episode_no: int | None = None


class InteractionBus:
    """Collects interaction intents during a tick and executes them serially."""

    def __init__(self) -> None:
        self._pending: list[InteractionRequest] = []
        self._seen_pairs: set[str] = set()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def has_pending_kind(self, kind: InteractionKind) -> bool:
        return any(req.kind == kind for req in self._pending)

    def take_pending(self) -> list[InteractionRequest]:
        """Drain and return the pending queue (caller owns execution)."""
        queue = list(self._pending)
        self._pending.clear()
        return queue

    def enqueue(self, request: InteractionRequest) -> None:
        self._pending.append(request)

    def enqueue_kind(
        self,
        kind: InteractionKind,
        *,
        initiator_id: str,
        target_id: str | None = None,
        params: dict | None = None,
    ) -> InteractionRequest:
        request = InteractionRequest(
            request_id=new_id(),
            kind=kind,
            initiator_id=initiator_id,
            target_id=target_id,
            params=params or {},
        )
        self.enqueue(request)
        return request

    def collect_from_outcomes(
        self,
        world: WorldState,
        outcomes: Sequence[AgentTickOutcome],
    ) -> None:
        """Translate successful agent actions into interaction requests."""
        from agentcore.simulation.agents.tick_runner import AgentTickOutcome as _Outcome

        self._seen_pairs.clear()
        typed_outcomes: Sequence[_Outcome] = outcomes
        for outcome in typed_outcomes:
            action = outcome.action
            if outcome.error is not None or not action.success:
                continue
            if action.action == "speak_to" and action.tool_args:
                target_name = str(action.tool_args.get("target_name", "")).strip()
                message = str(action.tool_args.get("message", "")).strip()
                target = _agent_by_name(world, target_name)
                if target is None:
                    continue
                pair_key = _pair_key(action.agent_id, target.agent_id, "conversation")
                if pair_key in self._seen_pairs:
                    continue
                self._seen_pairs.add(pair_key)
                self.enqueue_kind(
                    "conversation",
                    initiator_id=action.agent_id,
                    target_id=target.agent_id,
                    params={"opening": message},
                )
            elif action.action == "propose_trade" and action.tool_args:
                target_name = str(action.tool_args.get("target_name", "")).strip()
                target = _agent_by_name(world, target_name)
                if target is None:
                    continue
                self.enqueue_kind(
                    "trade",
                    initiator_id=action.agent_id,
                    target_id=target.agent_id,
                    params={
                        "item": action.tool_args.get("item", "日用品"),
                        "quantity": action.tool_args.get("quantity", 1),
                        "price": action.tool_args.get("price", 10.0),
                        "buyer_is_initiator": action.tool_args.get("buyer_is_initiator", True),
                    },
                )
            elif action.action == "propose_vote" and action.tool_args:
                motion = str(action.tool_args.get("motion", "")).strip()
                if not motion:
                    continue
                if any(r.kind == "vote" for r in self._pending):
                    continue
                self.enqueue_kind(
                    "vote",
                    initiator_id=action.agent_id,
                    params={"motion": motion},
                )

    async def process_tick(self, ctx: InteractionTickContext) -> list[InteractionResult]:
        """Drain the queue serially; each protocol completes within this tick."""
        personas = {p.agent_id: p for p in ctx.personas}
        results: list[InteractionResult] = []
        queue = list(self._pending)
        self._pending.clear()

        for request in queue:
            if request.kind == "conversation":
                result = await run_conversation(
                    ConversationContext(
                        world=ctx.world,
                        personas=personas,
                        llm=ctx.llm,
                        model=ctx.model,
                    ),
                    request,
                )
            elif request.kind == "trade":
                result = await run_trade(
                    TradeContext(
                        world=ctx.world,
                        personas=personas,
                        llm=ctx.llm,
                        model=ctx.model,
                    ),
                    request,
                )
            elif request.kind == "vote":
                result = await run_vote(
                    VoteContext(
                        world=ctx.world,
                        personas=personas,
                        llm=ctx.llm,
                        model=ctx.model,
                    ),
                    request,
                )
            elif request.kind == "heart_pick":
                if ctx.show_season is None or ctx.show_episode_no is None:
                    result = InteractionResult(
                        request_id=request.request_id,
                        kind="heart_pick",
                        status="failed",
                        initiator_id=request.initiator_id,
                        target_id=request.target_id,
                        summary="heart_pick 缺少赛制状态",
                        detail="missing_show_season",
                    )
                else:
                    result = await run_heart_pick(
                        HeartPickContext(
                            world=ctx.world,
                            season=ctx.show_season,
                            episode_no=ctx.show_episode_no,
                            tick=ctx.tick,
                        ),
                        request,
                    )
            else:
                result = InteractionResult(
                    request_id=request.request_id,
                    kind=request.kind,
                    status="failed",
                    initiator_id=request.initiator_id,
                    target_id=request.target_id,
                    summary=f"未知交互类型：{request.kind}",
                )
            results.append(result)
            if ctx.on_result is not None:
                await ctx.on_result(result)
        return results


def _agent_by_name(world: WorldState, name: str):
    if not name:
        return None
    for agent in world.agents.values():
        if agent.name == name:
            return agent
    return None


def _pair_key(a: str, b: str, kind: str) -> str:
    left, right = sorted((a, b))
    return f"{kind}:{left}:{right}"
