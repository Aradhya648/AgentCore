"""Market trade protocol (BE-17)."""

from __future__ import annotations

from dataclasses import dataclass

from agentcore.llm.provider.protocol import LLMProvider
from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.agents.social import adjust_relation, clamp
from agentcore.simulation.interaction.llm_helpers import sim_complete_json
from agentcore.simulation.interaction.models import (
    InteractionRequest,
    InteractionResult,
    InteractionStateChange,
    InteractionTranscriptLine,
)
from agentcore.simulation.world.state import WorldAgent, WorldState

MARKET_LOCATION = "市场"
TRADE_MOOD_DELTA = 0.05
TRADE_RELATION_DELTA = 0.08


@dataclass(frozen=True)
class TradeContext:
    world: WorldState
    personas: dict[str, SimPersona]
    llm: LLMProvider
    model: str


def _agent(world: WorldState, agent_id: str) -> WorldAgent | None:
    return world.agents.get(agent_id)


def _inventory_summary(agent: WorldAgent) -> str:
    if not agent.inventory:
        return "空"
    return ", ".join(f"{k}×{v}" for k, v in sorted(agent.inventory.items()))


async def _decide_acceptance(
    ctx: TradeContext,
    *,
    buyer: WorldAgent,
    seller: WorldAgent,
    offer_item: str,
    offer_qty: int,
    price: float,
) -> tuple[bool, str]:
    seller_persona = ctx.personas.get(seller.agent_id)
    system = (
        f"{seller_persona.system_prompt if seller_persona else seller.name} "
        "你在市场决定是否接受一笔交易。只输出 JSON："
        '{"accept": true|false, "reason": "一句话"}'
    )
    user = (
        f"买家 {buyer.name} 想用 {price:.0f} 金币买你的 {offer_item}×{offer_qty}。"
        f"你现有：金币 {seller.money:.0f}，物品 {_inventory_summary(seller)}。"
        "是否接受？"
    )
    payload, _raw = await sim_complete_json(
        ctx.llm, model=ctx.model, system=system, user=user, temperature=0.5
    )
    if payload is None:
        return seller.inventory.get(offer_item, 0) >= offer_qty, "默认按库存判断"
    return bool(payload.get("accept", False)), str(payload.get("reason", "")).strip()


def _transfer_trade(
    seller: WorldAgent,
    buyer: WorldAgent,
    *,
    item: str,
    qty: int,
    price: float,
) -> str | None:
    if seller.inventory.get(item, 0) < qty:
        return f"{seller.name}的{item}不足"
    if buyer.money < price:
        return f"{buyer.name}金币不足"
    seller.inventory[item] = seller.inventory.get(item, 0) - qty
    if seller.inventory[item] <= 0:
        seller.inventory.pop(item, None)
    buyer.inventory[item] = buyer.inventory.get(item, 0) + qty
    seller.money += price
    buyer.money -= price
    return None


async def run_trade(ctx: TradeContext, request: InteractionRequest) -> InteractionResult:
    initiator = _agent(ctx.world, request.initiator_id)
    target_id = request.target_id
    if initiator is None or not target_id:
        return InteractionResult(
            request_id=request.request_id,
            kind="trade",
            status="failed",
            initiator_id=request.initiator_id,
            target_id=target_id,
            summary="交易方不存在",
        )
    target = _agent(ctx.world, target_id)
    if target is None:
        return InteractionResult(
            request_id=request.request_id,
            kind="trade",
            status="failed",
            initiator_id=initiator.agent_id,
            target_id=target_id,
            summary="交易对象不存在",
        )
    if initiator.location != MARKET_LOCATION or target.location != MARKET_LOCATION:
        return InteractionResult(
            request_id=request.request_id,
            kind="trade",
            status="failed",
            initiator_id=initiator.agent_id,
            target_id=target.agent_id,
            summary="交易仅可在市场进行",
        )

    item = str(request.params.get("item", "日用品")).strip() or "日用品"
    qty = max(1, int(request.params.get("quantity", 1)))
    price = float(request.params.get("price", 10.0))
    multiplier = getattr(ctx.world.modifiers, "market_price_multiplier", 1.0)
    if multiplier > 1.0:
        price = round(price * multiplier, 1)
    buyer, seller = (initiator, target) if request.params.get("buyer_is_initiator", True) else (
        target,
        initiator,
    )

    accepted, reason = await _decide_acceptance(
        ctx,
        buyer=buyer,
        seller=seller,
        offer_item=item,
        offer_qty=qty,
        price=price,
    )
    proposal = (
        f"{buyer.name} 出价 {price:.0f} 金币购买 {seller.name} 的 {item}×{qty}"
    )
    if not accepted:
        return InteractionResult(
            request_id=request.request_id,
            kind="trade",
            status="rejected",
            initiator_id=initiator.agent_id,
            target_id=target.agent_id,
            summary=f"交易被拒：{reason or proposal}",
            transcript=[
                InteractionTranscriptLine(
                    speaker_id=initiator.agent_id,
                    speaker_name=initiator.name,
                    text=proposal,
                    round=0,
                )
            ],
        )

    async with ctx.world.mutation_lock():
        error = _transfer_trade(seller, buyer, item=item, qty=qty, price=price)
        if error:
            return InteractionResult(
                request_id=request.request_id,
                kind="trade",
                status="failed",
                initiator_id=initiator.agent_id,
                target_id=target.agent_id,
                summary=f"交易失败：{error}",
                detail=error,
            )
        buyer.mood = clamp(buyer.mood + TRADE_MOOD_DELTA, -1.0, 1.0)
        seller.mood = clamp(seller.mood + TRADE_MOOD_DELTA, -1.0, 1.0)
        adjust_relation(buyer, seller.agent_id, TRADE_RELATION_DELTA)
        adjust_relation(seller, buyer.agent_id, TRADE_RELATION_DELTA)
        summary = (
            f"tick{ctx.world.tick} 成交：{buyer.name}←{seller.name} "
            f"{item}×{qty} @{price:.0f}币"
        )
        ctx.world.event_log.append(summary)

    return InteractionResult(
        request_id=request.request_id,
        kind="trade",
        status="completed",
        initiator_id=initiator.agent_id,
        target_id=target.agent_id,
        summary=summary,
        transcript=[
            InteractionTranscriptLine(
                speaker_id=initiator.agent_id,
                speaker_name=initiator.name,
                text=proposal,
                round=0,
            )
        ],
        state_changes=InteractionStateChange(
            mood_deltas={
                buyer.agent_id: TRADE_MOOD_DELTA,
                seller.agent_id: TRADE_MOOD_DELTA,
            },
            relation_deltas=[
                (buyer.agent_id, seller.agent_id, TRADE_RELATION_DELTA),
                (seller.agent_id, buyer.agent_id, TRADE_RELATION_DELTA),
            ],
            money_transfers=[
                {"from": buyer.agent_id, "to": seller.agent_id, "amount": price}
            ],
            inventory_transfers=[
                {"from": seller.agent_id, "to": buyer.agent_id, "item": item, "quantity": qty}
            ],
        ),
    )
