"""Deterministic scripted tick decisions (no LLM).

Opt-in / fallback path for demo & local dev when DeepSeek is unavailable
or ``SIMULATION_SCRIPTED`` / run ``scripted`` is set. Residents follow the
town hourly schedule (role overrides included): move when the schedule
location differs, otherwise stay and perform the slot activity.

Non-protagonist residents get deterministic schedule dispersion (persona /
``agent_id`` hash): varied activity copy and staggered public landings so
the town does not read as a chorus of identical stay/move lines. Story
cast (Zhao / Wang / Liu) keep schedule locations so demo-pulse geography
stays predictable between beats.

Still produces ``AgentTickOutcome`` so the service can emit the same
``sim.agent_action`` / ``sim.agent_state`` SSE events as the LLM path.

Additionally, every ``SCRIPTED_DEMO_INTERVAL`` ticks a lightweight demo
pulse advances a fixed multi-beat story arc (Zhao↔Wang market rivalry,
Liu mediation, town-hall vote) via conversation / trade / vote
interactions and story-aligned preset ``world_event``s — so Unity demos
stay readable without DeepSeek. Cadence is intentionally a bit sparse
(interaction every 4 ticks, world_event every 8) so beats remain readable.

God-mode injects (storm / festival / price_surge / announcement) alter
the *next* scripted tick: shelter / gather / market bias, and queued
announcement votes are drained deterministically.

Story beats / world presets: single SoT ``packages/town-story-packs`` →
``pnpm gen:story-packs`` → packaged ``agentcore.simulation.data``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agentcore.core.types import new_id
from agentcore.simulation.agents.models import SimPersona
from agentcore.simulation.agents.social import adjust_relation, clamp
from agentcore.simulation.agents.story_packs import (
    DEMO_PACK_FESTIVAL,
    DEMO_PACK_IDS,
    DEMO_PACK_PRICE_SURGE,
    DEMO_PACK_TOWN_HALL,
    Speaker,
    StoryBeat,
    TradeSpec,
    beats_for_pack,
    normalize_demo_pack,
    presets_for_pack,
)
from agentcore.simulation.agents.tick_runner import AgentTickOutcome
from agentcore.simulation.interaction.models import (
    InteractionRequest,
    InteractionResult,
    InteractionStateChange,
    InteractionTranscriptLine,
)
from agentcore.simulation.scenarios.town.schedule import (
    ROLE_HOURLY_OVERRIDES,
    ScheduleSlot,
    schedule_hint_for_persona,
)
from agentcore.simulation.types import SimAgentAction
from agentcore.simulation.world.events.models import WorldEvent
from agentcore.simulation.world.events.templates import build_preset_event
from agentcore.simulation.world.state import WorldAgent, WorldState

if TYPE_CHECKING:
    from agentcore.simulation.interaction.bus import InteractionBus

# Demo pulse cadence (ticks). Interaction every N; world_event every 2N.
# 4/8 gives readable gaps between story beats without starving Unity demos.
SCRIPTED_DEMO_INTERVAL = 4
SCRIPTED_WORLD_EVENT_INTERVAL = SCRIPTED_DEMO_INTERVAL * 2

# Re-export pack ids for callers / tests (SoT lives in story_packs).
__all__ = [
    "SCRIPTED_DEMO_INTERVAL",
    "SCRIPTED_WORLD_EVENT_INTERVAL",
    "DEMO_PACK_PRICE_SURGE",
    "DEMO_PACK_FESTIVAL",
    "DEMO_PACK_TOWN_HALL",
    "DEMO_PACK_IDS",
    "normalize_demo_pack",
    "run_scripted_agent_tick",
    "run_scripted_ticks",
    "run_scripted_demo_pulse",
    "drain_scripted_pending",
]

_RIVAL_LEFT = "zhao"
_RIVAL_RIGHT = "wang"
_MEDIATOR = "liu"
_STORY_CAST = frozenset({_RIVAL_LEFT, _RIVAL_RIGHT, _MEDIATOR})
_MARKET = "市场"
_SQUARE = "广场"
_TOWN_HALL = "镇政厅"
_HOME = "住宅区"
_SHELTER_REGIONS = frozenset({_HOME, _TOWN_HALL, "面包店", "餐厅", "图书馆", "工坊"})
_PUBLIC_GATHER = (_SQUARE, _MARKET, "公园", "图书馆", "工坊", "码头")
# Hours where everyone should stay put (sleep / late home) — no location jitter.
_ANCHOR_HOURS = frozenset({0, 1, 2, 3, 4, 5, 19, 21, 22, 23})
# Shared public landings → deterministic alternates so non-cast don't pile up.
_LOCATION_ALTERNATES: dict[str, tuple[str, ...]] = {
    "公园": ("公园", "广场", "码头", _HOME),
    "广场": ("广场", "公园", _MARKET, "图书馆"),
    "市场": (_MARKET, "广场", "餐厅", "码头"),
    "餐厅": ("餐厅", _MARKET, "广场"),
    "图书馆": ("图书馆", "公园", "广场", "工坊"),
    "工坊": ("工坊", "码头", "图书馆", _MARKET),
    "码头": ("码头", "公园", "广场", "工坊"),
    "面包店": ("面包店", _MARKET, "广场"),
    _TOWN_HALL: (_TOWN_HALL, "广场", "图书馆"),
    _HOME: (_HOME, "公园", "广场"),
}
# When dispersion moves someone off the town-wide default, pick a local activity.
_LOCATION_IDLE_ACTIVITIES: dict[str, tuple[str, ...]] = {
    "公园": ("散步", "歇脚", "晒太阳", "看人下棋"),
    "广场": ("闲逛", "听街坊聊天", "看热闹", "活动筋骨"),
    "市场": ("逛摊", "询价", "看行情", "帮腔闲聊"),
    "餐厅": ("找位子歇脚", "看看今日菜", "等人吃饭"),
    "图书馆": ("翻书", "安静坐读", "看报"),
    "工坊": ("看手作", "闻木香逛逛", "跟师傅打招呼"),
    "码头": ("吹风", "看船", "岸边走走"),
    "面包店": ("闻香路过", "看看橱窗", "买点面包"),
    "镇政厅": ("办事路过", "看公告栏", "等熟人"),
    "住宅区": ("在家歇着", "门口坐坐", "收拾屋子"),
}
# Exact activity copy variants (same hour, different residents).
_ACTIVITY_VARIANTS: dict[str, tuple[str, ...]] = {
    "睡觉": ("睡觉", "安睡", "熟睡中"),
    "起床洗漱": ("起床洗漱", "洗漱整理", "慢悠悠起床"),
    "做早饭": ("做早饭", "准备早餐", "热一壶水做饭"),
    "开门准备": ("开门准备", "收拾门面", "开张前准备"),
    "早市开张": ("早市开张", "张罗早市", "招呼早客"),
    "晨练聚集": ("晨练聚集", "跟着晨练", "广场活动筋骨"),
    "买卖高峰": ("买卖高峰", "忙着招呼客人", "盯着摊位行情"),
    "午餐营业": ("午餐营业", "张罗午饭", "忙午饭高峰"),
    "午休散步": ("午休散步", "饭后溜达", "树荫下歇脚", "公园歇息"),
    "午后阅览": ("午后阅览", "翻书看报", "安静坐读"),
    "手作忙碌": ("手作忙碌", "打磨手作", "忙活木器"),
    "闲聊社交": ("闲聊社交", "跟街坊寒暄", "听镇里八卦", "广场唠嗑"),
    "公务办理": ("公务办理", "跑一趟镇政厅", "办点镇上的事"),
    "傍晚散步": ("傍晚散步", "吹晚风散步", "码头边走走", "晚饭前溜达"),
    "晚餐高峰": ("晚餐高峰", "张罗晚饭", "忙晚饭客人"),
    "回家休息": ("回家休息", "收工回家", "回屋歇着"),
    "晚间散步": ("晚间散步", "晚饭后散步", "夜色里走走"),
    "居家放松": ("居家放松", "在家歇着", "屋里闲坐"),
    "洗漱就寝": ("洗漱就寝", "准备睡觉", "洗漱收工"),
    "入睡": ("入睡", "熄灯睡觉", "沉沉睡去"),
    "和面开炉": ("和面开炉", "揉面备炉", "开炉烤面包"),
    "出炉摆柜": ("出炉摆柜", "摆上面包", "出炉上架"),
    "取定制托盘": ("取定制托盘", "去工坊取托盘", "取订做的托盘"),
    "下棋": ("下棋", "公园对弈", "找人杀一盘"),
    "读报借书": ("读报借书", "翻报借书", "图书馆读报"),
    "午后读书会": ("午后读书会", "参加读书会", "听读书分享"),
    "晒太阳聊天": ("晒太阳聊天", "晒暖闲聊", "坐着唠家常"),
    "守店揽客": ("守店揽客", "看店招呼", "守着摊位"),
    "订做货箱": ("订做货箱", "去订货箱", "工坊谈货箱"),
    "盘点库存": ("盘点库存", "清点存货", "核对着货架"),
    "摆摊卖菜": ("摆摊卖菜", "卖新鲜菜", "招呼买菜的"),
    "看木器摊": ("看木器摊", "逛工坊木器", "看手作摊"),
    "收摊后散步": ("收摊后散步", "收摊吹风", "收完摊走走"),
    "巡逻": ("巡逻", "广场巡一圈", "留意街面动静"),
    "巡查岸边": ("巡查岸边", "码头巡岸", "查看岸边情况"),
    "维持秩序": ("维持秩序", "市场维持秩序", "劝散拥堵"),
    "傍晚巡岸": ("傍晚巡岸", "傍晚巡码头", "岸边再走一遭"),
    "后厨忙": ("后厨忙", "灶上忙活", "准备午市菜"),
    "查菜谱灵感": ("查菜谱灵感", "翻菜谱找灵感", "图书馆查菜谱"),
    "看海鲜到货": ("看海鲜到货", "码头看海鲜", "盯着到货"),
    "招待客人": ("招待客人", "招呼晚饭客人", "张罗堂食"),
    "整理借阅": ("整理借阅", "归架整理", "理借阅台"),
    "主持阅览": ("主持阅览", "照看阅览室", "接待读者"),
    "读者服务": ("读者服务", "帮读者找书", "答借阅问题"),
    "上门随访": ("上门随访", "入户随访", "看望住户"),
    "健康讲座资料": ("健康讲座资料", "整理讲座材料", "查健康资料"),
    "健康咨询": ("健康咨询", "广场义诊咨询", "解答健康问题"),
    "开炉备料": ("开炉备料", "备料开炉", "工坊备料"),
    "打磨木器": ("打磨木器", "细细打磨", "修整木器"),
    "接待访客": ("接待访客", "招呼来看手作的", "工坊待客"),
    "手作高峰": ("手作高峰", "赶手作订单", "忙手作活"),
    "收工清扫": ("收工清扫", "清扫工坊", "收工整理"),
    "整理公文": ("整理公文", "批阅公文", "整理镇政材料"),
    "查看货运": ("查看货运", "码头看货运", "核对到港货物"),
    "查档阅卷": ("查档阅卷", "图书馆查档", "翻阅卷宗"),
    "接待来访": ("接待来访", "镇政厅接待", "见来访镇民"),
    "傍晚巡视": ("傍晚巡视", "傍晚巡一圈", "码头巡视"),
    "节日聚集": ("节日聚集", "凑节日热闹", "跟镇民同乐", "看庆典"),
    "因风暴避险": ("因风暴避险", "躲雨避险", "暂避风雨"),
    "关注涨价行情": ("关注涨价行情", "盯涨价盘口", "打听进货价"),
    "参加镇政厅表决": ("参加镇政厅表决", "到场参加表决", "等候投票议题"),
}


def _stable_mix(*parts: object) -> int:
    """FNV-1a style mix — deterministic across processes (no PYTHONHASHSEED)."""
    h = 2166136261
    for part in parts:
        for ch in str(part):
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
    return h


def _pick_variant(key: str, variants: tuple[str, ...], *salt: object) -> str:
    if not variants:
        return key
    return variants[_stable_mix(key, *salt) % len(variants)]


def _flavor_activity(persona: SimPersona, hour: int, activity: str) -> str:
    variants = _ACTIVITY_VARIANTS.get(activity)
    if variants is None:
        return activity
    return _pick_variant(activity, variants, persona.agent_id, hour % 24, "act")


def _scripted_schedule_slot(persona: SimPersona, hour: int) -> ScheduleSlot:
    """Schedule slot with deterministic non-cast dispersion (location + activity)."""
    base = schedule_hint_for_persona(persona, hour)
    hour_key = hour % 24
    activity = _flavor_activity(persona, hour_key, base.activity)

    # Story cast: keep canonical landings for demo-pulse continuity.
    if persona.agent_id in _STORY_CAST:
        return ScheduleSlot(location=base.location, activity=activity)

    # Role workplace hours + night/home anchors: keep location, vary copy only.
    role_hours = ROLE_HOURLY_OVERRIDES.get(persona.role, {})
    if hour_key in role_hours or hour_key in _ANCHOR_HOURS:
        return ScheduleSlot(location=base.location, activity=activity)

    alts = _LOCATION_ALTERNATES.get(base.location, (base.location,))
    dest = _pick_variant(base.location, alts, persona.agent_id, hour_key, "loc")
    if dest != base.location:
        idle = _LOCATION_IDLE_ACTIVITIES.get(dest, (f"在{dest}晃悠",))
        activity = _pick_variant(dest, idle, persona.agent_id, hour_key, "idle")
    return ScheduleSlot(location=dest, activity=activity)


async def run_scripted_agent_tick(
    *,
    world: WorldState,
    persona: SimPersona,
) -> AgentTickOutcome:
    """Advance one resident by schedule + active world modifiers (deterministic)."""
    t0 = time.monotonic()
    agent = world.agents[persona.agent_id]
    override = _modifier_destination(world, persona, agent)
    if override is not None:
        dest, activity, reason = override
        activity = _flavor_activity(persona, world.hour, activity)
        return await _emit_move_or_stay(
            world=world,
            persona=persona,
            agent=agent,
            dest=dest,
            activity=activity,
            reason=reason,
            t0=t0,
        )

    slot = _scripted_schedule_slot(persona, world.hour)
    return await _emit_move_or_stay(
        world=world,
        persona=persona,
        agent=agent,
        dest=slot.location,
        activity=slot.activity,
        reason="scripted_schedule",
        t0=t0,
    )


async def _emit_move_or_stay(
    *,
    world: WorldState,
    persona: SimPersona,
    agent: WorldAgent,
    dest: str,
    activity: str,
    reason: str,
    t0: float,
) -> AgentTickOutcome:
    moved = agent.location != dest
    if moved:
        old = agent.location
        await world.set_location(persona.agent_id, dest)
        await world.update_agent_activity(persona.agent_id, f"前往{dest}")
        thought = _thought_for_reason(reason, old=old, dest=dest, activity=activity)
        detail = f"scripted move_to {dest} ({reason})"
        action = SimAgentAction(
            agent_id=persona.agent_id,
            action="move_to",
            thought=thought,
            tool_name="move_to",
            tool_args={"destination": dest, "reason": reason},
            success=True,
            detail=detail,
        )
        await world.record(
            f"tick{world.tick} {agent.name} 按脚本从{old}走到{dest}（{activity}·{reason}）"
        )
    else:
        await world.update_agent_activity(persona.agent_id, activity)
        thought = _thought_for_reason(reason, old=dest, dest=dest, activity=activity)
        detail = f"scripted stay_here {activity} ({reason})"
        action = SimAgentAction(
            agent_id=persona.agent_id,
            action="stay_here",
            thought=thought,
            tool_name="stay_here",
            tool_args={"activity": activity, "reason": reason},
            success=True,
            detail=detail,
        )
        await world.record(
            f"tick{world.tick} {agent.name} 按脚本在{dest}{activity}（{reason}）"
        )

    async with world.mutation_lock():
        world.agents[persona.agent_id].last_thought = thought

    return AgentTickOutcome(
        action=action,
        rounds=0,
        latency_ms=int((time.monotonic() - t0) * 1000),
        usage={},
        cost_usd=0.0,
    )


def _thought_for_reason(
    reason: str, *, old: str, dest: str, activity: str
) -> str:
    if reason == "storm_shelter":
        if old != dest:
            return f"暴风雨来了，从{old}赶往{dest}避险。"
        return f"暴风雨中留在{dest}避险，暂缓户外活动。"
    if reason == "festival_gather":
        if old != dest:
            return f"节日气氛浓，从{old}前往{dest}与镇民同乐。"
        return f"留在{dest}参与节日聚集。"
    if reason == "price_surge_market":
        if old != dest:
            return f"物价上涨，赶往{dest}看行情、谈进货。"
        return f"涨价风中留在{dest}盯盘口与交易。"
    if reason == "announcement_vote":
        if old != dest:
            return f"镇政厅有公告议题，从{old}前往{dest}参加表决。"
        return f"留在{dest}等待投票议题。"
    if old != dest:
        return f"按日程从{old}前往{dest}，准备{activity}。"
    return f"按日程留在{dest}，继续{activity}。"


def _modifier_destination(
    world: WorldState,
    persona: SimPersona,
    agent: WorldAgent,
) -> tuple[str, str, str] | None:
    """Return (dest, activity, reason) when world modifiers override schedule."""
    mods = world.modifiers
    if _has_pending_vote(world):
        return _TOWN_HALL, "参加镇政厅表决", "announcement_vote"
    if mods.storm_active:
        dest = _shelter_destination(persona, agent)
        return dest, "因风暴避险", "storm_shelter"
    if mods.festival_active:
        dest = _gather_destination(persona, agent)
        return dest, "节日聚集", "festival_gather"
    if mods.market_price_multiplier > 1.05 and _is_market_role(persona, agent):
        return _MARKET, "关注涨价行情", "price_surge_market"
    return None


def _has_pending_vote(world: WorldState) -> bool:
    bus = getattr(world, "interaction_bus", None)
    if bus is None:
        return False
    has_kind = getattr(bus, "has_pending_kind", None)
    if callable(has_kind):
        return bool(has_kind("vote"))
    return False


def _shelter_destination(persona: SimPersona, agent: WorldAgent) -> str:
    if agent.location in _SHELTER_REGIONS:
        return agent.location
    home = (persona.location or "").strip()
    if home in _SHELTER_REGIONS:
        return home
    if agent.role in ("镇长秘书", "镇派出所民警"):
        return _TOWN_HALL
    return _HOME


def _gather_destination(persona: SimPersona, agent: WorldAgent) -> str:
    if agent.location in _PUBLIC_GATHER:
        return agent.location
    # Stagger slightly by agent id so not everyone stacks on one cell.
    idx = sum(ord(c) for c in persona.agent_id) % len(_PUBLIC_GATHER)
    return _PUBLIC_GATHER[idx]


def _is_market_role(persona: SimPersona, agent: WorldAgent) -> bool:
    if persona.agent_id in (_RIVAL_LEFT, _RIVAL_RIGHT):
        return True
    blob = f"{agent.role}{persona.goal}"
    return any(token in blob for token in ("商", "贩", "市场", "进货", "卖"))


async def run_scripted_ticks(
    *,
    world: WorldState,
    personas: list[SimPersona],
) -> list[AgentTickOutcome]:
    """Run scripted decisions for every persona (activation already applied)."""
    outcomes: list[AgentTickOutcome] = []
    for persona in personas:
        if persona.agent_id not in world.agents:
            continue
        outcomes.append(await run_scripted_agent_tick(world=world, persona=persona))
    return outcomes


async def run_scripted_demo_pulse(
    world: WorldState,
    *,
    demo_pack: str | None = None,
) -> tuple[list[InteractionResult], list[WorldEvent]]:
    """Emit the next beat of the scripted rivalry arc for Unity demos.

    Called only on the scripted path. Every ``SCRIPTED_DEMO_INTERVAL`` ticks
    produces one conversation / trade / vote; every
    ``SCRIPTED_WORLD_EVENT_INTERVAL`` ticks also injects a story-aligned
    preset world event.

    ``demo_pack`` selects the story arc (``price_surge`` | ``festival`` |
    ``town_hall``). Prefer ``world.demo_pack`` when unset. Not part of REST
    create schema — packs load from packaged JSON (``pnpm gen:story-packs``);
    default remains ``price_surge``.
    """
    tick = world.tick
    if tick <= 0 or tick % SCRIPTED_DEMO_INTERVAL != 0:
        return [], []

    pack = normalize_demo_pack(
        demo_pack if demo_pack is not None else getattr(world, "demo_pack", None)
    )
    beats = beats_for_pack(pack)
    presets = presets_for_pack(pack)

    interactions: list[InteractionResult] = []
    world_events: list[WorldEvent] = []

    pulse_index = tick // SCRIPTED_DEMO_INTERVAL
    beat = beats[(pulse_index - 1) % len(beats)]
    pair = _pick_demo_pair(world)
    if pair is not None:
        left, right = pair
        result = await _play_story_beat(world, left, right, beat)
        interactions.append(result)

    if tick % SCRIPTED_WORLD_EVENT_INTERVAL == 0:
        preset = presets[(tick // SCRIPTED_WORLD_EVENT_INTERVAL - 1) % len(presets)]
        event = build_preset_event(preset, tick=tick)
        event.source = "scripted_demo"
        # Only attach story blurbs when the beat's causal blurb matches this preset
        # (avoids festival copy on a recycled price_surge after the 9-beat arc wraps).
        if beat.world_event_blurb and _blurb_matches_preset(beat.world_event_blurb, preset):
            event.description = beat.world_event_blurb
        world_events.append(event)

    return interactions, world_events


async def drain_scripted_pending(
    world: WorldState,
    interaction_bus: InteractionBus,
) -> list[InteractionResult]:
    """Deterministically complete queued interactions (esp. announcement votes).

    Scripted path never calls ``InteractionBus.process_tick`` (LLM protocols).
    Announcement injects enqueue votes on the bus — drain them here so they
    are not dropped.
    """
    pending: list[InteractionRequest] = interaction_bus.take_pending()
    if not pending:
        return []

    results: list[InteractionResult] = []
    for request in pending:
        if request.kind == "vote":
            motion = str(request.params.get("motion", "")).strip() or (
                "是否同意下周举办镇民大会？"
            )
            results.append(
                await _run_scripted_vote(
                    world,
                    initiator_id=request.initiator_id,
                    motion=motion,
                    detail="scripted_announcement_vote",
                    arc_label=None,
                )
            )
        else:
            results.append(
                InteractionResult(
                    request_id=request.request_id,
                    kind=request.kind,
                    status="cancelled",
                    initiator_id=request.initiator_id,
                    target_id=request.target_id,
                    summary=f"scripted 路径跳过非投票排队交互：{request.kind}",
                    detail="scripted_skip",
                )
            )
    return results


def _blurb_matches_preset(blurb: str, preset: str) -> bool:
    if preset == "price_surge":
        return any(token in blurb for token in ("价格", "涨价", "物价"))
    if preset == "storm":
        return any(token in blurb for token in ("暴风", "雨", "避险"))
    if preset == "festival":
        return any(token in blurb for token in ("节日", "庆典", "广场张灯"))
    if preset == "announcement":
        return any(token in blurb for token in ("公告", "镇政厅", "表决", "镇民大会"))
    return False


def _pick_demo_pair(world: WorldState) -> tuple[WorldAgent, WorldAgent] | None:
    """Prefer the seeded rivals (Zhao/Wang); else colocated pair; else any two."""
    left = world.agents.get(_RIVAL_LEFT)
    right = world.agents.get(_RIVAL_RIGHT)
    if left is not None and right is not None:
        return left, right

    agents = list(world.agents.values())
    if len(agents) < 2:
        return None
    by_loc: dict[str, list[WorldAgent]] = {}
    for agent in agents:
        by_loc.setdefault(agent.location, []).append(agent)
    for group in by_loc.values():
        if len(group) >= 2:
            return group[0], group[1]
    return agents[0], agents[1]


async def _play_story_beat(
    world: WorldState,
    initiator: WorldAgent,
    target: WorldAgent,
    beat: StoryBeat,
) -> InteractionResult:
    if beat.kind == "trade":
        return await _scripted_story_trade(world, initiator, target, beat)
    if beat.kind == "vote":
        motion = beat.vote_motion or "是否临时限价并延长夜市开放时间？"
        # Prefer beat.summary_template (pack-specific); arc_label only for non-beat votes.
        return await _run_scripted_vote(
            world,
            initiator_id=_vote_initiator_id(world),
            motion=motion,
            detail="scripted_demo",
            arc_label=None,
            beat=beat,
            rivals=(initiator, target),
        )
    return await _scripted_story_conversation(world, initiator, target, beat)


def _vote_initiator_id(world: WorldState) -> str:
    for agent in world.agents.values():
        if agent.role == "镇长秘书":
            return agent.agent_id
    mediator = world.agents.get(_MEDIATOR)
    if mediator is not None:
        return mediator.agent_id
    return next(iter(world.agents))


def _build_transcript(
    initiator: WorldAgent,
    target: WorldAgent,
    lines: tuple[tuple[Speaker, str], ...],
    *,
    mediator: WorldAgent | None = None,
) -> list[InteractionTranscriptLine]:
    transcript: list[InteractionTranscriptLine] = []
    for round_i, (speaker, text) in enumerate(lines):
        if speaker == "mediator" and mediator is not None:
            agent = mediator
        elif speaker == "target":
            agent = target
        else:
            agent = initiator
        transcript.append(
            InteractionTranscriptLine(
                speaker_id=agent.agent_id,
                speaker_name=agent.name,
                text=text,
                round=round_i,
            )
        )
    return transcript


async def _ensure_colocated(
    world: WorldState,
    initiator: WorldAgent,
    target: WorldAgent,
    *,
    location: str | None = None,
) -> tuple[WorldAgent, WorldAgent]:
    dest = location or initiator.location
    if initiator.location != dest:
        await world.set_location(initiator.agent_id, dest)
        initiator = world.agents[initiator.agent_id]
    if target.location != dest:
        await world.set_location(target.agent_id, dest)
        target = world.agents[target.agent_id]
    return initiator, target


async def _scripted_story_conversation(
    world: WorldState,
    initiator: WorldAgent,
    target: WorldAgent,
    beat: StoryBeat,
) -> InteractionResult:
    location = beat.location or _MARKET
    initiator, target = await _ensure_colocated(
        world, initiator, target, location=location
    )
    mediator: WorldAgent | None = None
    if beat.include_mediator:
        mediator = world.agents.get(_MEDIATOR)
        if mediator is not None and mediator.location != location:
            await world.set_location(mediator.agent_id, location)
            mediator = world.agents[mediator.agent_id]

    transcript = _build_transcript(
        initiator, target, beat.lines, mediator=mediator
    )
    mood_i, mood_t, rel = beat.mood_initiator, beat.mood_target, beat.relation

    async with world.mutation_lock():
        initiator.mood = clamp(initiator.mood + mood_i, -1.0, 1.0)
        target.mood = clamp(target.mood + mood_t, -1.0, 1.0)
        adjust_relation(initiator, target.agent_id, rel)
        adjust_relation(target, initiator.agent_id, rel)
        if mediator is not None:
            mediator.mood = clamp(mediator.mood + 0.03, -1.0, 1.0)
        summary = beat.summary_template.format(
            tick=world.tick, a=initiator.name, b=target.name
        )
        world.event_log.append(summary)

    return InteractionResult(
        request_id=new_id(),
        kind="conversation",
        status="completed",
        initiator_id=initiator.agent_id,
        target_id=target.agent_id,
        summary=summary,
        transcript=transcript,
        state_changes=InteractionStateChange(
            mood_deltas={
                initiator.agent_id: mood_i,
                target.agent_id: mood_t,
            },
            relation_deltas=[
                (initiator.agent_id, target.agent_id, rel),
                (target.agent_id, initiator.agent_id, rel),
            ],
        ),
        detail="scripted_demo",
    )


async def _scripted_story_trade(
    world: WorldState,
    initiator: WorldAgent,
    target: WorldAgent,
    beat: StoryBeat,
) -> InteractionResult:
    initiator, target = await _ensure_colocated(
        world, initiator, target, location=beat.location or _MARKET
    )
    spec = beat.trade or TradeSpec(item="日用品", qty=1, base_price=10.0)
    item, qty = spec.item, spec.qty
    price = spec.base_price
    multiplier = getattr(world.modifiers, "market_price_multiplier", 1.0)
    if multiplier > 1.0:
        price = round(price * multiplier, 1)

    buyer, seller = initiator, target
    if seller.inventory.get(item, 0) < qty:
        seller.inventory[item] = seller.inventory.get(item, 0) + qty
    if buyer.money < price:
        buyer.money = price

    transcript = _build_transcript(initiator, target, beat.lines)
    mood_i, mood_t, rel = beat.mood_initiator, beat.mood_target, beat.relation

    async with world.mutation_lock():
        seller.inventory[item] = seller.inventory.get(item, 0) - qty
        if seller.inventory[item] <= 0:
            seller.inventory.pop(item, None)
        buyer.inventory[item] = buyer.inventory.get(item, 0) + qty
        seller.money += price
        buyer.money -= price
        buyer.mood = clamp(buyer.mood + mood_i, -1.0, 1.0)
        seller.mood = clamp(seller.mood + mood_t, -1.0, 1.0)
        adjust_relation(buyer, seller.agent_id, rel)
        adjust_relation(seller, buyer.agent_id, rel)
        summary = beat.summary_template.format(
            tick=world.tick,
            a=buyer.name,
            b=seller.name,
            item=item,
            qty=qty,
            price=price,
        )
        if multiplier > 1.0 and "涨价" not in summary:
            summary = f"{summary}（市价×{multiplier:.1f}）"
        world.event_log.append(summary)

    return InteractionResult(
        request_id=new_id(),
        kind="trade",
        status="completed",
        initiator_id=initiator.agent_id,
        target_id=target.agent_id,
        summary=summary,
        transcript=transcript,
        state_changes=InteractionStateChange(
            mood_deltas={
                buyer.agent_id: mood_i,
                seller.agent_id: mood_t,
            },
            relation_deltas=[
                (buyer.agent_id, seller.agent_id, rel),
                (seller.agent_id, buyer.agent_id, rel),
            ],
            money_transfers=[
                {"from": buyer.agent_id, "to": seller.agent_id, "amount": price}
            ],
            inventory_transfers=[
                {
                    "from": seller.agent_id,
                    "to": buyer.agent_id,
                    "item": item,
                    "quantity": qty,
                }
            ],
        ),
        detail="scripted_demo",
    )


async def _run_scripted_vote(
    world: WorldState,
    *,
    initiator_id: str,
    motion: str,
    detail: str,
    arc_label: str | None,
    beat: StoryBeat | None = None,
    rivals: tuple[WorldAgent, WorldAgent] | None = None,
) -> InteractionResult:
    """Deterministic town-hall vote (no LLM) for scripted / announcement paths."""
    initiator = world.agents.get(initiator_id)
    if initiator is None:
        initiator = next(iter(world.agents.values()))
        initiator_id = initiator.agent_id

    # Gather a quorum at town hall.
    gather_ids = {initiator_id, _RIVAL_LEFT, _RIVAL_RIGHT, _MEDIATOR}
    for agent_id in list(gather_ids):
        if agent_id in world.agents and world.agents[agent_id].location != _TOWN_HALL:
            await world.set_location(agent_id, _TOWN_HALL)
    # Ensure at least two agents present.
    present = [a for a in world.agents.values() if a.location == _TOWN_HALL]
    if len(present) < 2:
        for agent in world.agents.values():
            if agent.location != _TOWN_HALL:
                await world.set_location(agent.agent_id, _TOWN_HALL)
            present = [a for a in world.agents.values() if a.location == _TOWN_HALL]
            if len(present) >= 2:
                break

    initiator = world.agents[initiator_id]
    voters = [a for a in world.agents.values() if a.location == _TOWN_HALL]

    transcript: list[InteractionTranscriptLine] = []
    if beat is not None and rivals is not None:
        left, right = rivals
        mediator = world.agents.get(_MEDIATOR)
        transcript = _build_transcript(
            left, right, beat.lines, mediator=mediator
        )

    yes_votes = 0
    no_votes = 0
    abstain_votes = 0
    for voter in voters:
        choice, reason = _scripted_vote_choice(voter, motion)
        if choice == "yes":
            yes_votes += 1
        elif choice == "no":
            no_votes += 1
        else:
            abstain_votes += 1
        label = {"yes": "支持", "no": "反对", "abstain": "弃权"}[choice]
        # Avoid duplicating story lines already in transcript.
        if beat is None:
            transcript.append(
                InteractionTranscriptLine(
                    speaker_id=voter.agent_id,
                    speaker_name=voter.name,
                    text=f"{label}：{reason}",
                    round=len(transcript),
                )
            )

    if yes_votes > no_votes:
        outcome = "通过"
    elif no_votes > yes_votes:
        outcome = "否决"
    else:
        outcome = "平局"

    if beat is not None:
        summary = beat.summary_template.format(
            tick=world.tick,
            motion=motion,
            outcome=outcome,
            yes=yes_votes,
            no=no_votes,
            abstain=abstain_votes,
        )
    else:
        label_suffix = f"（{arc_label}）" if arc_label else ""
        summary = (
            f"tick{world.tick} 投票「{motion}」→ {outcome} "
            f"(支持{yes_votes}/反对{no_votes}/弃权{abstain_votes}){label_suffix}"
        )

    mood_i = beat.mood_initiator if beat is not None else 0.03
    mood_t = beat.mood_target if beat is not None else 0.03
    rel = beat.relation if beat is not None else 0.0

    async with world.mutation_lock():
        world.governance.last_motion = motion
        world.governance.last_outcome = outcome
        world.governance.yes_votes = yes_votes
        world.governance.no_votes = no_votes
        world.governance.abstain_votes = abstain_votes
        if outcome == "通过" and motion not in world.governance.policies:
            world.governance.policies.append(motion)
        world.event_log.append(summary)
        for voter in voters:
            voter.mood = clamp(voter.mood + 0.03, -1.0, 1.0)
        if rivals is not None and rel != 0.0:
            left, right = rivals
            left = world.agents[left.agent_id]
            right = world.agents[right.agent_id]
            left.mood = clamp(left.mood + mood_i, -1.0, 1.0)
            right.mood = clamp(right.mood + mood_t, -1.0, 1.0)
            adjust_relation(left, right.agent_id, rel)
            adjust_relation(right, left.agent_id, rel)

    state = InteractionStateChange(
        governance={
            "motion": motion,
            "outcome": outcome,
            "yes": yes_votes,
            "no": no_votes,
            "abstain": abstain_votes,
        }
    )
    if rivals is not None and rel != 0.0:
        left, right = rivals
        state.mood_deltas = {
            left.agent_id: mood_i,
            right.agent_id: mood_t,
        }
        state.relation_deltas = [
            (left.agent_id, right.agent_id, rel),
            (right.agent_id, left.agent_id, rel),
        ]

    return InteractionResult(
        request_id=new_id(),
        kind="vote",
        status="completed",
        initiator_id=initiator.agent_id,
        summary=summary,
        transcript=transcript,
        state_changes=state,
        detail=detail,
    )


def _scripted_vote_choice(voter: WorldAgent, motion: str) -> tuple[str, str]:
    """Deterministic ballot from role / mood (no LLM)."""
    role = voter.role or ""
    if "民警" in role or "秘书" in role:
        return "yes", "按镇政厅程序支持治理议题"
    if voter.agent_id in (_RIVAL_LEFT, _RIVAL_RIGHT):
        return "yes", "与其继续吵，不如用规矩把价稳住"
    if voter.mood < -0.35:
        return "abstain", "心情不佳，暂不表态"
    if "商" in role or "贩" in role:
        return "yes" if "限价" in motion or "夜市" in motion else "no", "看生意影响"
    return "yes", "同意镇政厅安排"
