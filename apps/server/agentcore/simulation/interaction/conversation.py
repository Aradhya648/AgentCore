"""Free-form two-agent conversation protocol (BE-16)."""

from __future__ import annotations

from dataclasses import dataclass

from agentcore.llm.provider.protocol import LLMProvider
from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.agents.social import adjust_relation, clamp
from agentcore.simulation.interaction.llm_helpers import sim_complete_json, sim_complete_text
from agentcore.simulation.interaction.models import (
    InteractionRequest,
    InteractionResult,
    InteractionStateChange,
    InteractionTranscriptLine,
)
from agentcore.simulation.world.state import WorldAgent, WorldState

CONVERSATION_MIN_ROUNDS = 3
CONVERSATION_MAX_ROUNDS = 5
CONVERSATION_MOOD_DELTA = 0.12
CONVERSATION_RELATION_DELTA = 0.1


@dataclass(frozen=True)
class ConversationContext:
    world: WorldState
    personas: dict[str, SimPersona]
    llm: LLMProvider
    model: str


def _agent(world: WorldState, agent_id: str) -> WorldAgent | None:
    return world.agents.get(agent_id)


async def _accept_invitation(
    ctx: ConversationContext,
    *,
    initiator: WorldAgent,
    target: WorldAgent,
    opening: str,
) -> tuple[bool, str]:
    target_persona = ctx.personas.get(target.agent_id)
    system = (
        f"{target_persona.system_prompt if target_persona else target.name} "
        "你现在要决定是否接受对方的对话邀请。只输出 JSON："
        '{"accept": true|false, "reason": "一句话"}'
    )
    user = (
        f"tick {ctx.world.tick}，你在{target.location}。"
        f"{initiator.name}对你说：「{opening}」。是否愿意聊几句？"
    )
    payload, _raw = await sim_complete_json(
        ctx.llm, model=ctx.model, system=system, user=user, temperature=0.6
    )
    if payload is None:
        return True, "默认接受"
    return bool(payload.get("accept", True)), str(payload.get("reason", "")).strip()


async def _speak_line(
    ctx: ConversationContext,
    *,
    speaker: WorldAgent,
    listener: WorldAgent,
    history: list[InteractionTranscriptLine],
    round_no: int,
) -> str:
    persona = ctx.personas.get(speaker.agent_id)
    lines = "\n".join(f"{line.speaker_name}: {line.text}" for line in history[-6:])
    system = (
        f"{persona.system_prompt if persona else speaker.name} "
        "你正在小镇里与另一位居民对话。用一两句中文口语回复，符合人设，不要复读。"
    )
    user = (
        f"地点：{speaker.location}。对话对象：{listener.name}。\n"
        f"近期对话：\n{lines or '（刚开始）'}\n"
        f"请说第 {round_no} 轮你的话。"
    )
    return await sim_complete_text(
        ctx.llm, model=ctx.model, system=system, user=user, temperature=0.85
    )


async def run_conversation(
    ctx: ConversationContext,
    request: InteractionRequest,
) -> InteractionResult:
    initiator = _agent(ctx.world, request.initiator_id)
    target_id = request.target_id
    if initiator is None or not target_id:
        return InteractionResult(
            request_id=request.request_id,
            kind="conversation",
            status="failed",
            initiator_id=request.initiator_id,
            target_id=target_id,
            summary="对话发起者不存在",
            detail="missing initiator or target",
        )
    target = _agent(ctx.world, target_id)
    if target is None:
        return InteractionResult(
            request_id=request.request_id,
            kind="conversation",
            status="failed",
            initiator_id=initiator.agent_id,
            target_id=target_id,
            summary="对话对象不存在",
        )
    if initiator.location != target.location:
        return InteractionResult(
            request_id=request.request_id,
            kind="conversation",
            status="failed",
            initiator_id=initiator.agent_id,
            target_id=target.agent_id,
            summary=f"{initiator.name}与{target.name}不在同一地点",
        )

    opening = str(request.params.get("opening", "")).strip() or "你好，聊几句？"
    accepted, reason = await _accept_invitation(
        ctx, initiator=initiator, target=target, opening=opening
    )
    if not accepted:
        return InteractionResult(
            request_id=request.request_id,
            kind="conversation",
            status="rejected",
            initiator_id=initiator.agent_id,
            target_id=target.agent_id,
            summary=f"{target.name}拒绝了对话：{reason or '不方便'}",
            transcript=[
                InteractionTranscriptLine(
                    speaker_id=initiator.agent_id,
                    speaker_name=initiator.name,
                    text=opening,
                    round=0,
                )
            ],
        )

    transcript: list[InteractionTranscriptLine] = [
        InteractionTranscriptLine(
            speaker_id=initiator.agent_id,
            speaker_name=initiator.name,
            text=opening,
            round=0,
        )
    ]
    total_rounds = min(
        CONVERSATION_MAX_ROUNDS,
        max(
            CONVERSATION_MIN_ROUNDS,
            int(request.params.get("max_rounds", CONVERSATION_MIN_ROUNDS)),
        ),
    )
    speakers = [initiator, target]
    for round_no in range(1, total_rounds + 1):
        speaker = speakers[round_no % 2]
        listener = speakers[(round_no + 1) % 2]
        line = await _speak_line(
            ctx,
            speaker=speaker,
            listener=listener,
            history=transcript,
            round_no=round_no,
        )
        if not line:
            break
        transcript.append(
            InteractionTranscriptLine(
                speaker_id=speaker.agent_id,
                speaker_name=speaker.name,
                text=line,
                round=round_no,
            )
        )

    async with ctx.world.mutation_lock():
        initiator.mood = clamp(initiator.mood + CONVERSATION_MOOD_DELTA, -1.0, 1.0)
        target.mood = clamp(target.mood + CONVERSATION_MOOD_DELTA * 0.8, -1.0, 1.0)
        adjust_relation(initiator, target.agent_id, CONVERSATION_RELATION_DELTA)
        adjust_relation(target, initiator.agent_id, CONVERSATION_RELATION_DELTA)
        summary_line = (
            f"tick{ctx.world.tick} {initiator.name}与{target.name}聊了{len(transcript)}句"
        )
        ctx.world.event_log.append(summary_line)

    return InteractionResult(
        request_id=request.request_id,
        kind="conversation",
        status="completed",
        initiator_id=initiator.agent_id,
        target_id=target.agent_id,
        summary=summary_line,
        transcript=transcript,
        state_changes=InteractionStateChange(
            mood_deltas={
                initiator.agent_id: CONVERSATION_MOOD_DELTA,
                target.agent_id: CONVERSATION_MOOD_DELTA * 0.8,
            },
            relation_deltas=[
                (initiator.agent_id, target.agent_id, CONVERSATION_RELATION_DELTA),
                (target.agent_id, initiator.agent_id, CONVERSATION_RELATION_DELTA),
            ],
        ),
    )
