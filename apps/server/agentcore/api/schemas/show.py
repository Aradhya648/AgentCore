"""恋综节目 REST schemas。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PublishStatus = Literal["draft", "review", "published", "archived"]


class ShowEpisodeSummary(BaseModel):
    episode_id: str
    season_id: str
    episode_no: int
    title: str
    run_id: str
    tick_start: int
    tick_end: int
    publish_status: PublishStatus
    tagline: str | None = None
    quiz_focus: str | None = None


class ShowEpisodeListResponse(BaseModel):
    data: list[ShowEpisodeSummary]
    total: int


class ShowManifestResponse(BaseModel):
    """EpisodeManifest JSON — shape mirrors contract-types episodeManifest."""

    manifest: dict[str, Any]


class SubmitShowQuizRequest(BaseModel):
    guess: str = Field(..., min_length=1)


class ShowQuizSettlementResponse(BaseModel):
    correct: bool
    guess: str
    answer: str
    monologue: str | None = None
    monologue_who: str | None = None


class PatchShowEpisodePublishRequest(BaseModel):
    publish_status: PublishStatus
