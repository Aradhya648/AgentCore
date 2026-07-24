"""Town hall vote protocol (BE-18)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agentcore.llm.provider.protocol import LLMProvider
from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.interaction.llm_helpers import sim_complete_json
from agentcore.simulation.interaction.models import (
    InteractionRequest,
    InteractionResult,
    InteractionStateChange,
    InteractionTranscriptLine,
)
from agentcore.simulation.world.state import WorldAgent, WorldState

TOWN_HALL = "镇政厅"
VoteChoice = Literal["yes", "no", "abstain"]


@dataclass(frozen=True)
class VoteContext:
    world: WorldState
    personas: dict[str, SimPersona]
    llm: LLMProvider
    model: str


async def _cast_vote(
    ctx: VoteContext,
    *,
    voter: WorldAgent,
    motion: str,
) -> tuple[VoteChoice, str]:
    persona = ctx.personas.get(voter.agent_id)
    system = (
        f"{persona.system_prompt if persona else voter.name} "
        "你在镇政厅对议题投票。只输出 JSON："
        '{"vote": "yes"|"no"|"abstain", "reason": "一句话"}'
    )
    user = (
        f"议题：{motion}\n"
        f"你的心情 {voter.mood:+.1f}，职业 {voter.role}，目标 {voter.goal}。"
        "请投票。"
    )
    payload, _raw = await sim_complete_json(
        ctx.llm, model=ctx.model, system=system, user=user, temperature=0.6
    )
    if payload is None:
        return "abstain", "无法解析，弃权"
    raw_vote = str(payload.get("vote", "abstain")).strip().lower()
    if raw_vote not in ("yes", "no", "abstain"):
        raw_vote = "abstain"
    return raw_vote, str(payload.get("reason", "")).strip()  # type: ignore[return-value]


async def run_vote(ctx: VoteContext, request: InteractionRequest) -> InteractionResult:
    initiator = ctx.world.agents.get(request.initiator_id)
    if initiator is None:
        return InteractionResult(
            request_id=request.request_id,
            kind="vote",
            status="failed",
            initiator_id=request.initiator_id,
            summary="投票发起人不存在",
        )
    if initiator.location != TOWN_HALL:
        return InteractionResult(
            request_id=request.request_id,
            kind="vote",
            status="failed",
            initiator_id=initiator.agent_id,
            summary="投票只能在镇政厅发起",
        )

    motion = str(request.params.get("motion", "")).strip() or "是否同意本周市场休市一天？"
    voters = [a for a in ctx.world.agents.values() if a.location == TOWN_HALL]
    if len(voters) < 2:
        return InteractionResult(
            request_id=request.request_id,
            kind="vote",
            status="failed",
            initiator_id=initiator.agent_id,
            summary="镇政厅在场人数不足，无法投票",
        )

    transcript: list[InteractionTranscriptLine] = []
    yes_votes = 0
    no_votes = 0
    abstain_votes = 0
    for voter in voters:
        choice, reason = await _cast_vote(ctx, voter=voter, motion=motion)
        if choice == "yes":
            yes_votes += 1
        elif choice == "no":
            no_votes += 1
        else:
            abstain_votes += 1
        label = {"yes": "支持", "no": "反对", "abstain": "弃权"}[choice]
        transcript.append(
            InteractionTranscriptLine(
                speaker_id=voter.agent_id,
                speaker_name=voter.name,
                text=f"{label}：{reason or motion}",
                round=len(transcript),
            )
        )

    if yes_votes > no_votes:
        outcome = "通过"
    elif no_votes > yes_votes:
        outcome = "否决"
    else:
        outcome = "平局"

    summary = (
        f"tick{ctx.world.tick} 投票「{motion}」→ {outcome} "
        f"(支持{yes_votes}/反对{no_votes}/弃权{abstain_votes})"
    )
    async with ctx.world.mutation_lock():
        ctx.world.governance.last_motion = motion
        ctx.world.governance.last_outcome = outcome
        ctx.world.governance.yes_votes = yes_votes
        ctx.world.governance.no_votes = no_votes
        ctx.world.governance.abstain_votes = abstain_votes
        if outcome == "通过" and motion not in ctx.world.governance.policies:
            ctx.world.governance.policies.append(motion)
        ctx.world.event_log.append(summary)
        for voter in voters:
            voter.mood = min(1.0, voter.mood + 0.03)

    return InteractionResult(
        request_id=request.request_id,
        kind="vote",
        status="completed",
        initiator_id=initiator.agent_id,
        summary=summary,
        transcript=transcript,
        state_changes=InteractionStateChange(
            governance={
                "motion": motion,
                "outcome": outcome,
                "yes": yes_votes,
                "no": no_votes,
                "abstain": abstain_votes,
            }
        ),
    )
