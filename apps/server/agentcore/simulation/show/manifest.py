"""EpisodeManifest pydantic mirror（对齐 packages/contract-types episodeManifest.ts）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

EPISODE_MANIFEST_VERSION = 1

EpisodeSegmentKind = Literal[
    "recap", "day", "night", "ceremony", "quiz", "reveal", "epilogue"
]
EpisodeCameraKind = Literal[
    "wide_establish", "follow_pair", "orbit_group", "push_in", "reveal_closeup"
]
EpisodeRelationKind = Literal[
    "spark", "oneway", "tension", "cooling", "chaos", "unknown"
]


class EpisodeTickSpan(BaseModel):
    start: int
    end: int


class EpisodeRelationHint(BaseModel):
    from_: str = Field(alias="from")
    to: str
    kind: EpisodeRelationKind
    label: str

    model_config = {"populate_by_name": True}


class EpisodeShot(BaseModel):
    id: str
    camera: EpisodeCameraKind
    subjects: list[str] = Field(default_factory=list)
    tick_at: int
    duration_hint_ms: int | None = None


class EpisodeOverlay(BaseModel):
    """Loose overlay — kind-discriminated at validation time via dict passthrough helpers."""

    kind: str
    id: str | None = None
    text: str | None = None
    sub: str | None = None
    who: str | None = None
    title: str | None = None
    time: str | None = None
    present: list[str] | None = None
    mood: Literal["day", "fire", "night"] | None = None
    hints: list[dict[str, Any]] | None = None
    tick_at: int | None = None
    shot_id: str | None = None

    model_config = {"extra": "allow"}


class EpisodeSegment(BaseModel):
    id: str
    kind: EpisodeSegmentKind
    label: str | None = None
    tick_span: EpisodeTickSpan
    shots: list[EpisodeShot] = Field(default_factory=list)
    overlays: list[dict[str, Any]] = Field(default_factory=list)


class EpisodeQuiz(BaseModel):
    focus: str
    question: str
    hint: str | None = None
    options: list[str]
    answer: str
    insert_at: dict[str, Any] = Field(default_factory=dict)


class EpisodeRevealStep(BaseModel):
    who: str
    pick: str
    note: str | None = None


class EpisodeReveal(BaseModel):
    intro: str | None = None
    steps: list[EpisodeRevealStep] = Field(default_factory=list)
    outro: list[str] = Field(default_factory=list)
    answer_overlay_id: str | None = None


class EpisodeHighlight(BaseModel):
    id: str
    title: str
    quote: str
    by: str
    shot_id: str | None = None
    overlay_id: str | None = None


class EpisodeNextTeaser(BaseModel):
    title: str
    hook: str


class EpisodeManifest(BaseModel):
    version: int = EPISODE_MANIFEST_VERSION
    season: str
    episode_no: int
    title: str
    run_id: str
    tick_range: EpisodeTickSpan
    tagline: str | None = None
    rule_line: str | None = None
    segments: list[EpisodeSegment] = Field(default_factory=list)
    quiz: EpisodeQuiz | None = None
    reveal: EpisodeReveal | None = None
    highlights: list[EpisodeHighlight] = Field(default_factory=list)
    next_teaser: EpisodeNextTeaser
