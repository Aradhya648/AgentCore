"""恋综赛制状态与 wire 友好模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PublishStatus = Literal["draft", "review", "published", "archived"]
GatePhase = Literal[
    "recap",
    "day",
    "night",
    "ceremony",
    "quiz",
    "reveal",
    "epilogue",
]


class HeartPick(BaseModel):
    """One sealed (or revealed) heart pick."""

    from_agent_id: str
    to_agent_id: str
    public: bool = False
    episode_no: int


class PairBond(BaseModel):
    agent_a_id: str
    agent_b_id: str
    formed_episode: int
    affection_shifted: bool = False
    affection_shift_episode: int | None = None


class EpisodeRecord(BaseModel):
    episode_no: int
    picks: list[HeartPick] = Field(default_factory=list)
    pairs_formed: list[PairBond] = Field(default_factory=list)
    zero_vote_agents: list[str] = Field(default_factory=list)
    departed: list[str] = Field(default_factory=list)
    awkward_kind: str | None = None
    quiz_focus: str | None = None
    tick_span_start: int = 0
    tick_span_end: int = 0


class ShowSeasonState(BaseModel):
    """Mutable season rules state (persisted on run.config['show'])."""

    season_id: str = "心动小镇"
    season_title: str = "心动小镇"
    current_episode: int = 1
    active_agent_ids: list[str] = Field(default_factory=list)
    # agent_id → consecutive zero-vote streak (before departure).
    zero_vote_streak: dict[str, int] = Field(default_factory=dict)
    pairs: list[PairBond] = Field(default_factory=list)
    departed: list[str] = Field(default_factory=list)
    episodes: list[EpisodeRecord] = Field(default_factory=list)
    # Sealed picks for the in-progress episode (pre-reveal).
    sealed_picks: list[HeartPick] = Field(default_factory=list)
    seed: int = 0
    run_id: str = ""


class EpisodeTickPlan(BaseModel):
    """Orchestrator output: tick windows + constraints for one episode."""

    episode_no: int
    tick_start: int
    tick_end: int
    gates: dict[GatePhase, tuple[int, int]]
    date_pairs: list[tuple[str, str]]
    date_locations: dict[str, str]  # agent_id → location for day
    night_location: str
    quiz_focus: str | None
    allowed_picks: dict[str, list[str]]  # voter → allowed targets
    sealed_secrets: list[str]
    leak_allowed: list[str]
    awkward_kind: str | None = None
    departure_rule: bool = True
    public_vote_required: bool = False


class ShowEpisodeMeta(BaseModel):
    """Catalog row for 节目 API — includes publish gate slot."""

    episode_id: str
    season_id: str
    episode_no: int
    title: str
    run_id: str
    tick_start: int
    tick_end: int
    publish_status: PublishStatus = "draft"
    tagline: str | None = None
    quiz_focus: str | None = None


class QuizSubmission(BaseModel):
    episode_id: str
    user_id: str
    guess: str


class QuizSettlement(BaseModel):
    correct: bool
    guess: str
    answer: str
    monologue: str | None = None
    monologue_who: str | None = None
