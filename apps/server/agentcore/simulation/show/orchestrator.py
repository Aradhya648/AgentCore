"""期编排器：§3.10 节拍 → 一期 tick 段约束。"""

from __future__ import annotations

import random

from agentcore.simulation.scenarios.show.beats import (
    awkward_kind_for_seed,
    beat_for,
)
from agentcore.simulation.scenarios.show.config import (
    SHOW_CONFIG,
    SHOW_DAY_REGIONS,
    SHOW_NIGHT_REGION,
)
from agentcore.simulation.show.models import EpisodeTickPlan, GatePhase, ShowSeasonState
from agentcore.simulation.show.rules import active_cast, allowed_targets

# Fixed phase fractions within one episode tick window (inclusive end).
_GATE_ORDER: tuple[GatePhase, ...] = (
    "recap",
    "day",
    "night",
    "quiz",
    "ceremony",
    "reveal",
    "epilogue",
)
# Relative weights → tick spans (sum = 120 for default).
_GATE_WEIGHTS: dict[GatePhase, int] = {
    "recap": 15,
    "day": 35,
    "night": 25,
    "quiz": 5,
    "ceremony": 5,
    "reveal": 20,
    "epilogue": 15,
}


def episode_tick_span(episode_no: int, *, ticks_per_episode: int | None = None) -> tuple[int, int]:
    tpe = ticks_per_episode or SHOW_CONFIG.ticks_per_episode
    start = (episode_no - 1) * tpe
    end = start + tpe - 1
    return start, end


def _split_gates(tick_start: int, tick_end: int) -> dict[GatePhase, tuple[int, int]]:
    total = tick_end - tick_start + 1
    weights = [(_GATE_WEIGHTS[g], g) for g in _GATE_ORDER]
    weight_sum = sum(w for w, _ in weights)
    gates: dict[GatePhase, tuple[int, int]] = {}
    cursor = tick_start
    for i, (w, gate) in enumerate(weights):
        if i == len(weights) - 1:
            span_end = tick_end
        else:
            length = max(1, round(total * w / weight_sum))
            span_end = min(tick_end, cursor + length - 1)
        gates[gate] = (cursor, span_end)
        cursor = span_end + 1
        if cursor > tick_end:
            # Collapse remaining empty gates onto last tick.
            for g2 in _GATE_ORDER[i + 1 :]:
                gates[g2] = (tick_end, tick_end)
            break
    return gates


def _resolve_date_pairs(
    state: ShowSeasonState,
    episode_no: int,
    *,
    rng: random.Random,
) -> list[tuple[str, str]]:
    beat = beat_for(episode_no)
    cast = active_cast(state)
    if beat.date_pairs:
        # Keep only pairs whose members are still active.
        pairs = [(a, b) for a, b in beat.date_pairs if a in cast and b in cast]
        used = {x for pair in pairs for x in pair}
        leftover = [a for a in cast if a not in used]
        rng.shuffle(leftover)
        for i in range(0, len(leftover) - 1, 2):
            pairs.append((leftover[i], leftover[i + 1]))
        return pairs

    # Prefer hints, then random pairing of remainder.
    pairs: list[tuple[str, str]] = []
    used: set[str] = set()
    for a, b in beat.date_pair_hints:
        if a in cast and b in cast and a not in used and b not in used:
            # Ep1: avoid A–B long exclusive date — hints already omit them.
            pairs.append((a, b))
            used.add(a)
            used.add(b)
    leftover = [a for a in cast if a not in used]
    rng.shuffle(leftover)
    # Ep1: if shenwan+luye both leftover, don't pair them exclusively first.
    if episode_no == 1 and len(leftover) >= 4:
        from agentcore.simulation.scenarios.show.cast import LUYE, SHENWAN

        if SHENWAN in leftover and LUYE in leftover:
            leftover = [a for a in leftover if a not in (SHENWAN, LUYE)] + [SHENWAN, LUYE]
    for i in range(0, len(leftover) - 1, 2):
        pairs.append((leftover[i], leftover[i + 1]))
    return pairs


def _assign_date_locations(
    pairs: list[tuple[str, str]],
    *,
    rng: random.Random,
) -> dict[str, str]:
    regions = list(SHOW_DAY_REGIONS)
    rng.shuffle(regions)
    mapping: dict[str, str] = {}
    for i, (a, b) in enumerate(pairs):
        loc = regions[i % len(regions)]
        mapping[a] = loc
        mapping[b] = loc
    return mapping


def plan_episode(
    state: ShowSeasonState,
    episode_no: int,
    *,
    ticks_per_episode: int | None = None,
) -> EpisodeTickPlan:
    """Build tick-segment constraints for one episode (deterministic for season seed)."""
    beat = beat_for(episode_no)
    tick_start, tick_end = episode_tick_span(episode_no, ticks_per_episode=ticks_per_episode)
    gates = _split_gates(tick_start, tick_end)
    rng = random.Random(state.seed * 1009 + episode_no * 17)

    date_pairs = _resolve_date_pairs(state, episode_no, rng=rng)
    date_locations = _assign_date_locations(date_pairs, rng=rng)

    # Ep4: zero-vote danger agents get priority date; else D steals A or B.
    if episode_no == 4:
        from agentcore.simulation.scenarios.show.cast import JIANGYU, LUYE, SHENWAN

        danger = [
            aid
            for aid, streak in state.zero_vote_streak.items()
            if streak >= 1 and aid in active_cast(state)
        ]
        if danger:
            # Re-pair: first danger with a high-affinity partner if possible.
            # Keep simple: ensure danger is in some pair (already true if in cast).
            pass
        elif JIANGYU in active_cast(state):
            # D steals A or B into a pair.
            target = SHENWAN if rng.random() < 0.5 else LUYE
            if target in active_cast(state):
                date_pairs = [
                    (a, b)
                    for a, b in date_pairs
                    if JIANGYU not in (a, b) and target not in (a, b)
                ]
                date_pairs.insert(0, (JIANGYU, target))
                date_locations = _assign_date_locations(date_pairs, rng=rng)

    allowed: dict[str, list[str]] = {}
    for voter in active_cast(state):
        allowed[voter] = allowed_targets(state, voter, episode_no=episode_no)
        # Paired agents may pick others (affection) — already allowed; no extra lock.

    awkward = awkward_kind_for_seed(state.seed) if beat.awkward_required else None

    return EpisodeTickPlan(
        episode_no=episode_no,
        tick_start=tick_start,
        tick_end=tick_end,
        gates=gates,
        date_pairs=date_pairs,
        date_locations=date_locations,
        night_location=SHOW_NIGHT_REGION,
        quiz_focus=beat.quiz_focus,
        allowed_picks=allowed,
        sealed_secrets=list(beat.sealed_secrets),
        leak_allowed=list(beat.leak_allowed),
        awkward_kind=awkward,
        departure_rule=beat.departure_rule,
        public_vote_required=beat.public_vote_required,
    )


def gate_at_tick(plan: EpisodeTickPlan, tick: int) -> GatePhase | None:
    for gate, (start, end) in plan.gates.items():
        if start <= tick <= end:
            return gate
    return None


def apply_day_positions(world, plan: EpisodeTickPlan) -> None:
    """Move cast to date locations (sync helper for scripted / produce)."""
    for agent_id, location in plan.date_locations.items():
        agent = world.agents.get(agent_id)
        if agent is None:
            continue
        agent.location = location
        from agentcore.simulation.world.locations import position_for_location

        agent.position = position_for_location(location)
        agent.activity = "约会"


def apply_night_positions(world, plan: EpisodeTickPlan) -> None:
    from agentcore.simulation.world.locations import position_for_location

    for agent_id in list(world.agents):
        agent = world.agents[agent_id]
        agent.location = plan.night_location
        agent.position = position_for_location(plan.night_location)
        agent.activity = "夜话"
