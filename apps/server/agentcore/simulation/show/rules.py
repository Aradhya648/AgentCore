"""赛制状态机：心动半公开、互选配对、移情标记、连续两期零票离场。"""

from __future__ import annotations

from agentcore.core.types import new_id
from agentcore.simulation.scenarios.show.beats import beat_for
from agentcore.simulation.scenarios.show.cast import SHOW_AGENT_IDS
from agentcore.simulation.show.models import (
    EpisodeRecord,
    HeartPick,
    PairBond,
    ShowSeasonState,
)


def new_season_state(
    *,
    seed: int = 0,
    run_id: str = "",
    season_id: str = "心动小镇",
    agent_ids: tuple[str, ...] | None = None,
) -> ShowSeasonState:
    ids = list(agent_ids or SHOW_AGENT_IDS)
    return ShowSeasonState(
        season_id=season_id,
        season_title=season_id,
        current_episode=1,
        active_agent_ids=ids,
        zero_vote_streak={aid: 0 for aid in ids},
        seed=seed,
        run_id=run_id or new_id(),
    )


def paired_partner(state: ShowSeasonState, agent_id: str) -> str | None:
    for bond in state.pairs:
        if bond.agent_a_id == agent_id:
            return bond.agent_b_id
        if bond.agent_b_id == agent_id:
            return bond.agent_a_id
    return None


def is_paired(state: ShowSeasonState, agent_id: str) -> bool:
    return paired_partner(state, agent_id) is not None


def active_cast(state: ShowSeasonState) -> list[str]:
    departed = set(state.departed)
    return [a for a in state.active_agent_ids if a not in departed]


def seal_pick(state: ShowSeasonState, *, from_id: str, to_id: str, episode_no: int) -> HeartPick:
    """Write a sealed heart pick (not yet public). Replaces prior sealed pick from same voter."""
    if from_id not in active_cast(state):
        raise ValueError(f"{from_id} is not active")
    if to_id not in active_cast(state):
        raise ValueError(f"{to_id} is not an active target")
    if from_id == to_id:
        raise ValueError("cannot pick self")
    state.sealed_picks = [p for p in state.sealed_picks if p.from_agent_id != from_id]
    pick = HeartPick(
        from_agent_id=from_id,
        to_agent_id=to_id,
        public=False,
        episode_no=episode_no,
    )
    state.sealed_picks.append(pick)
    return pick


def allowed_targets(
    state: ShowSeasonState,
    voter: str,
    *,
    episode_no: int,
) -> list[str]:
    """Allowed pick set for voter this episode (beat bias ∩ active cast − self − forbid)."""
    beat = beat_for(episode_no)
    cast = [a for a in active_cast(state) if a != voter]
    forbid = set(beat.pick_forbid.get(voter, []))
    cast = [a for a in cast if a not in forbid]
    bias = beat.pick_bias.get(voter)
    if not bias:
        return cast
    # Bias first, then remaining — still all allowed unless hard-forbid.
    ordered = [a for a in bias if a in cast]
    for a in cast:
        if a not in ordered:
            ordered.append(a)
    return ordered


def resolve_ceremony(
    state: ShowSeasonState,
    *,
    episode_no: int,
    awkward_kind: str | None = None,
    quiz_focus: str | None = None,
    tick_start: int = 0,
    tick_end: int = 0,
) -> EpisodeRecord:
    """End-of-episode ceremony: reveal picks, form pairs, affection, zero-vote, departure.

    Mutates ``state``. Returns the episode record.
    """
    beat = beat_for(episode_no)
    picks = list(state.sealed_picks)
    for p in picks:
        p.public = True

    pick_map = {p.from_agent_id: p.to_agent_id for p in picks}
    cast = active_cast(state)

    # Mutual picks → pair formed (if not already paired together).
    new_pairs: list[PairBond] = []
    seen_pair: set[frozenset[str]] = {frozenset((b.agent_a_id, b.agent_b_id)) for b in state.pairs}
    for a, b in list(pick_map.items()):
        if pick_map.get(b) == a:
            key = frozenset((a, b))
            if key not in seen_pair:
                bond = PairBond(agent_a_id=a, agent_b_id=b, formed_episode=episode_no)
                state.pairs.append(bond)
                new_pairs.append(bond)
                seen_pair.add(key)

    # Affection shift: paired agent picks someone else.
    affection_events: list[tuple[str, str]] = []
    for p in picks:
        # Partner check uses pairs *including* just-formed this night — affection only
        # if they were already paired *before* tonight's mutual (pre-existing bond).
        pre_existing = None
        for bond in state.pairs:
            if bond.formed_episode >= episode_no:
                continue
            if p.from_agent_id in (bond.agent_a_id, bond.agent_b_id):
                pre_existing = (
                    bond.agent_b_id if bond.agent_a_id == p.from_agent_id else bond.agent_a_id
                )
                break
        if pre_existing is not None and p.to_agent_id != pre_existing:
            for bond in state.pairs:
                if frozenset((bond.agent_a_id, bond.agent_b_id)) == frozenset(
                    (p.from_agent_id, pre_existing)
                ):
                    bond.affection_shifted = True
                    bond.affection_shift_episode = episode_no
            affection_events.append((p.from_agent_id, p.to_agent_id))

    # Received vote counts.
    received: dict[str, int] = {aid: 0 for aid in cast}
    for to_id in pick_map.values():
        if to_id in received:
            received[to_id] += 1

    zero_agents = [aid for aid, n in received.items() if n == 0]
    departed_now: list[str] = []

    if beat.departure_rule:
        for aid in cast:
            if aid in zero_agents:
                state.zero_vote_streak[aid] = state.zero_vote_streak.get(aid, 0) + 1
            else:
                state.zero_vote_streak[aid] = 0
            if state.zero_vote_streak.get(aid, 0) >= 2 and aid not in state.departed:
                state.departed.append(aid)
                departed_now.append(aid)
    else:
        for aid in cast:
            if aid not in zero_agents:
                state.zero_vote_streak[aid] = 0

    record = EpisodeRecord(
        episode_no=episode_no,
        picks=picks,
        pairs_formed=new_pairs,
        zero_vote_agents=zero_agents,
        departed=departed_now,
        awkward_kind=awkward_kind,
        quiz_focus=quiz_focus or beat.quiz_focus,
        tick_span_start=tick_start,
        tick_span_end=tick_end,
    )
    # Replace prior record for same episode_no if re-resolving.
    state.episodes = [e for e in state.episodes if e.episode_no != episode_no]
    state.episodes.append(record)
    state.episodes.sort(key=lambda e: e.episode_no)
    state.sealed_picks = []
    state.current_episode = max(state.current_episode, episode_no + 1)
    # Drop departed from active list (keep history in departed).
    state.active_agent_ids = [a for a in state.active_agent_ids if a not in state.departed]
    return record


def apply_scripted_picks(
    state: ShowSeasonState,
    picks: dict[str, str],
    *,
    episode_no: int,
) -> list[HeartPick]:
    """Seal a full ballot map (voter → target). Validates against allowed set."""
    sealed: list[HeartPick] = []
    for voter, target in picks.items():
        allowed = allowed_targets(state, voter, episode_no=episode_no)
        if target not in allowed:
            raise ValueError(
                f"pick {voter}→{target} not in allowed set {allowed} for ep{episode_no}"
            )
        sealed.append(seal_pick(state, from_id=voter, to_id=target, episode_no=episode_no))
    return sealed
