"""§3.10 七期节拍义务表 — 写死约束（约会分组 / 竞猜焦点 / 信息门闸 / 选票允许集）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentcore.simulation.scenarios.show.cast import (
    JIANGYU,
    LUYE,
    SHENWAN,
    XIEHENG,
    XUANAN,
    ZHOUKE,
)

AwkwardKind = Literal["misunderstanding", "boundary_probe", "cold_silence"]
Episode4Obligation = Literal["zero_vote_alert", "affection_seed"]


class EpisodeBeatSpec(BaseModel):
    """One episode's scripted obligations (§3.10)."""

    episode_no: int
    title: str
    emotion_arc: str
    # Fixed or preferred date pairs (agent_id, agent_id). Empty = free / random within cast.
    date_pairs: list[tuple[str, str]] = Field(default_factory=list)
    # Soft preference pairs when date_pairs is empty or partial.
    date_pair_hints: list[tuple[str, str]] = Field(default_factory=list)
    quiz_focus: str | None = None
    # Info gates: secrets that must stay sealed this episode.
    sealed_secrets: list[str] = Field(default_factory=list)
    # Secrets allowed to leak a first trace.
    leak_allowed: list[str] = Field(default_factory=list)
    # Per-voter preferred pick targets (soft bias for LLM / scripted).
    pick_bias: dict[str, list[str]] = Field(default_factory=dict)
    # Hard disallow list per voter (empty = only "not self" + not departed).
    pick_forbid: dict[str, list[str]] = Field(default_factory=dict)
    # Episode-specific flags.
    awkward_required: bool = False
    public_vote_required: bool = False
    departure_rule: bool = True  # False on episode 7
    fc_story_readable: bool = False  # F–C past must be clear by ep6
    notes: str = ""


# Secret keys used by info gates.
SECRET_FC_PAST = "f_c_past"


EPISODE_BEATS: dict[int, EpisodeBeatSpec] = {
    1: EpisodeBeatSpec(
        episode_no=1,
        title="亮相",
        emotion_arc="亮相 + 第一次心动试探",
        date_pair_hints=[(XUANAN, JIANGYU), (ZHOUKE, XIEHENG)],
        # A–B must not monopolize a long first date — omit them from forced pairs.
        quiz_focus=LUYE,
        sealed_secrets=[SECRET_FC_PAST],
        pick_bias={
            LUYE: [SHENWAN],
            SHENWAN: [LUYE, XIEHENG],
            XUANAN: [LUYE],
            JIANGYU: [SHENWAN, LUYE],
            ZHOUKE: [JIANGYU, XIEHENG],
            XIEHENG: [ZHOUKE, JIANGYU],
        },
        notes="六人亮相；A–B 不强绑首日长约会",
    ),
    2: EpisodeBeatSpec(
        episode_no=2,
        title="火花",
        emotion_arc="第一对约会出火花",
        date_pairs=[(SHENWAN, LUYE), (XUANAN, JIANGYU), (ZHOUKE, XIEHENG)],
        quiz_focus=SHENWAN,
        sealed_secrets=[SECRET_FC_PAST],
        pick_bias={
            LUYE: [SHENWAN],
            SHENWAN: [LUYE, ZHOUKE],
            XUANAN: [LUYE],
            JIANGYU: [SHENWAN, LUYE],
            ZHOUKE: [JIANGYU],
            XIEHENG: [ZHOUKE],
        },
        notes="强制 A–B 约会；夜话打趣主磕",
    ),
    3: EpisodeBeatSpec(
        episode_no=3,
        title="不对劲",
        emotion_arc="夜话第一次不对劲",
        date_pairs=[(LUYE, XUANAN), (SHENWAN, JIANGYU), (ZHOUKE, XIEHENG)],
        quiz_focus=XUANAN,
        sealed_secrets=[SECRET_FC_PAST],
        awkward_required=True,
        pick_bias={
            LUYE: [SHENWAN],
            SHENWAN: [XIEHENG, ZHOUKE],  # may avoid Luye after cold beat
            XUANAN: [XIEHENG, LUYE],
            JIANGYU: [XUANAN],
            ZHOUKE: [JIANGYU],
            XIEHENG: [ZHOUKE],
        },
        notes="强制 B–C 约会；不对劲三选一由种子定类型",
    ),
    4: EpisodeBeatSpec(
        episode_no=4,
        title="告急",
        emotion_arc="零票告急或移情苗头",
        date_pair_hints=[(JIANGYU, SHENWAN), (JIANGYU, LUYE)],
        quiz_focus=JIANGYU,
        sealed_secrets=[],
        leak_allowed=[SECRET_FC_PAST],
        pick_bias={
            LUYE: [SHENWAN],
            SHENWAN: [LUYE],
            XUANAN: [LUYE, XIEHENG],
            JIANGYU: [SHENWAN, LUYE],
            ZHOUKE: [XIEHENG, JIANGYU],
            XIEHENG: [XUANAN, ZHOUKE],
        },
        notes="F–C 允许第一缕痕迹；义务二选一由种子定",
    ),
    5: EpisodeBeatSpec(
        episode_no=5,
        title="公投夜",
        emotion_arc="公投 + 后果当场显现",
        quiz_focus=None,  # public vote card replaces quiz focus
        sealed_secrets=[],
        public_vote_required=True,
        leak_allowed=[SECRET_FC_PAST],
        notes="公投三选一；不讲清完整 F–C 故事",
    ),
    6: EpisodeBeatSpec(
        episode_no=6,
        title="洗牌",
        emotion_arc="公投余波 + 结局前洗牌",
        date_pairs=[(XUANAN, XIEHENG)],
        date_pair_hints=[(SHENWAN, LUYE)],
        quiz_focus=XIEHENG,
        sealed_secrets=[],
        fc_story_readable=True,
        pick_bias={
            XUANAN: [XIEHENG, LUYE],
            XIEHENG: [XUANAN],
            LUYE: [SHENWAN],
            SHENWAN: [LUYE],
            ZHOUKE: [XIEHENG, JIANGYU],
            JIANGYU: [XUANAN, SHENWAN],
        },
        notes="F–C 过往须可读；可出现真·移情投票",
    ),
    7: EpisodeBeatSpec(
        episode_no=7,
        title="结局夜",
        emotion_arc="确认或分开 / 最后心动",
        quiz_focus=None,  # binary main-line confirm optional
        sealed_secrets=[],
        departure_rule=False,
        fc_story_readable=True,
        notes="无离场规则；不写死最终 CP",
    ),
}


def beat_for(episode_no: int) -> EpisodeBeatSpec:
    if episode_no not in EPISODE_BEATS:
        raise KeyError(f"unknown episode_no={episode_no}")
    return EPISODE_BEATS[episode_no]


def awkward_kind_for_seed(seed: int) -> AwkwardKind:
    """§3.10 ep3: 误会 / 试探越界 / 当众冷场 — seed-stable pick."""
    kinds: tuple[AwkwardKind, ...] = ("misunderstanding", "boundary_probe", "cold_silence")
    return kinds[seed % 3]


def episode4_obligation_for_seed(seed: int) -> Episode4Obligation:
    return ("zero_vote_alert", "affection_seed")[seed % 2]
