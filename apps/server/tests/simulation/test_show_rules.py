"""恋综赛制状态机单测。"""

from __future__ import annotations

from agentcore.simulation.scenarios.show.cast import (
    JIANGYU,
    LUYE,
    SHENWAN,
    XIEHENG,
    XUANAN,
    ZHOUKE,
)
from agentcore.simulation.show.rules import (
    apply_scripted_picks,
    is_paired,
    new_season_state,
    resolve_ceremony,
    seal_pick,
)


def test_mutual_pick_forms_pair():
    state = new_season_state(seed=1)
    apply_scripted_picks(
        state,
        {LUYE: SHENWAN, SHENWAN: LUYE, XUANAN: ZHOUKE, ZHOUKE: XUANAN, JIANGYU: XIEHENG, XIEHENG: JIANGYU},
        episode_no=1,
    )
    record = resolve_ceremony(state, episode_no=1)
    assert any(
        {b.agent_a_id, b.agent_b_id} == {LUYE, SHENWAN} for b in record.pairs_formed
    )
    assert is_paired(state, LUYE)
    assert is_paired(state, SHENWAN)


def test_zero_vote_streak_departure():
    state = new_season_state(seed=2)
    # Ep1: everyone picks LUYE except LUYE picks SHENWAN → all but LUYE get votes?
    # Simpler: two episodes where XIEHENG receives zero.
    apply_scripted_picks(
        state,
        {
            LUYE: SHENWAN,
            SHENWAN: LUYE,
            XUANAN: LUYE,
            JIANGYU: SHENWAN,
            ZHOUKE: LUYE,
            XIEHENG: ZHOUKE,
        },
        episode_no=1,
    )
    r1 = resolve_ceremony(state, episode_no=1)
    assert XIEHENG in r1.zero_vote_agents
    assert XIEHENG not in r1.departed
    assert state.zero_vote_streak[XIEHENG] == 1

    apply_scripted_picks(
        state,
        {
            LUYE: SHENWAN,
            SHENWAN: LUYE,
            XUANAN: LUYE,
            JIANGYU: SHENWAN,
            ZHOUKE: LUYE,
            XIEHENG: JIANGYU,
        },
        episode_no=2,
    )
    r2 = resolve_ceremony(state, episode_no=2)
    assert XIEHENG in r2.zero_vote_agents
    assert XIEHENG in r2.departed
    assert XIEHENG in state.departed
    assert XIEHENG not in state.active_agent_ids


def test_affection_shift_when_paired_picks_other():
    state = new_season_state(seed=3)
    apply_scripted_picks(
        state,
        {LUYE: SHENWAN, SHENWAN: LUYE, XUANAN: JIANGYU, JIANGYU: XUANAN, ZHOUKE: XIEHENG, XIEHENG: ZHOUKE},
        episode_no=1,
    )
    resolve_ceremony(state, episode_no=1)
    assert is_paired(state, LUYE)

    # Ep2: Luye picks Xuanan while still paired with Shenwan → affection.
    apply_scripted_picks(
        state,
        {LUYE: XUANAN, SHENWAN: LUYE, XUANAN: LUYE, JIANGYU: ZHOUKE, ZHOUKE: JIANGYU, XIEHENG: ZHOUKE},
        episode_no=2,
    )
    resolve_ceremony(state, episode_no=2)
    bond = next(b for b in state.pairs if {b.agent_a_id, b.agent_b_id} == {LUYE, SHENWAN})
    assert bond.affection_shifted is True
    assert bond.affection_shift_episode == 2


def test_episode7_no_departure_rule():
    state = new_season_state(seed=7)
    # Force someone to streak 1, then ep7 zero again — should not depart.
    for aid in state.active_agent_ids:
        state.zero_vote_streak[aid] = 1
    # Minimal sealed picks: all pick LUYE except LUYE→SHENWAN so many get zero.
    for voter in list(state.active_agent_ids):
        target = SHENWAN if voter == LUYE else LUYE
        seal_pick(state, from_id=voter, to_id=target, episode_no=7)
    record = resolve_ceremony(state, episode_no=7)
    assert record.departed == []


def test_seal_pick_replaces_prior():
    state = new_season_state(seed=0)
    seal_pick(state, from_id=LUYE, to_id=SHENWAN, episode_no=1)
    seal_pick(state, from_id=LUYE, to_id=XUANAN, episode_no=1)
    assert len(state.sealed_picks) == 1
    assert state.sealed_picks[0].to_agent_id == XUANAN
