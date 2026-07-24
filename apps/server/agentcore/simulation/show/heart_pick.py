"""heart_pick 交互协议 — 密封选票写入赛制状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentcore.simulation.interaction.models import InteractionRequest, InteractionResult
from agentcore.simulation.show.rules import allowed_targets, seal_pick

if TYPE_CHECKING:
    from agentcore.simulation.show.models import ShowSeasonState
    from agentcore.simulation.world.state import WorldState


@dataclass
class HeartPickContext:
    world: WorldState
    season: ShowSeasonState
    episode_no: int
    tick: int


async def run_heart_pick(ctx: HeartPickContext, request: InteractionRequest) -> InteractionResult:
    """Resolve one heart_pick intent (LLM or scripted caller supplies target in params)."""
    target_id = request.target_id or str(request.params.get("to_agent_id", "")).strip()
    if not target_id:
        return InteractionResult(
            request_id=request.request_id,
            kind="heart_pick",
            status="rejected",
            initiator_id=request.initiator_id,
            target_id=None,
            summary="心动选票缺少目标",
            detail="missing_target",
        )
    allowed = allowed_targets(ctx.season, request.initiator_id, episode_no=ctx.episode_no)
    if target_id not in allowed:
        return InteractionResult(
            request_id=request.request_id,
            kind="heart_pick",
            status="rejected",
            initiator_id=request.initiator_id,
            target_id=target_id,
            summary=f"目标不在允许集合：{target_id}",
            detail="not_allowed",
        )
    try:
        pick = seal_pick(
            ctx.season,
            from_id=request.initiator_id,
            to_id=target_id,
            episode_no=ctx.episode_no,
        )
    except ValueError as exc:
        return InteractionResult(
            request_id=request.request_id,
            kind="heart_pick",
            status="rejected",
            initiator_id=request.initiator_id,
            target_id=target_id,
            summary=str(exc),
            detail="invalid_pick",
        )

    public = bool(request.params.get("public", False))
    if public:
        pick.public = True

    initiator = ctx.world.agents.get(request.initiator_id)
    target = ctx.world.agents.get(target_id)
    from_name = initiator.name if initiator else request.initiator_id
    to_name = target.name if target else target_id
    summary = (
        f"{from_name} 写下心动：{to_name}"
        if public
        else f"{from_name} 密封写下心动选票"
    )
    return InteractionResult(
        request_id=request.request_id,
        kind="heart_pick",
        status="completed",
        initiator_id=request.initiator_id,
        target_id=target_id,
        summary=summary,
        detail="sealed" if not public else "public",
    )
