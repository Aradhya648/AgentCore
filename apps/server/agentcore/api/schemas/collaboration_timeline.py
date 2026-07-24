"""项目级协作时间线（读时聚合投影）response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CollaborationTimelineAct(BaseModel):
    act_id: str
    kind: Literal["multi_agent", "debate"]
    title: str | None = None
    started_at: datetime | None = None


class CollaborationDossierRef(BaseModel):
    """Path-level 案卷消费事实（开赛注入或会话内 file_read）— 非跨会话过程边。"""

    path: str
    sources: list[Literal["dossier_inject", "file_read"]] = Field(default_factory=list)


class CollaborationTimelineItem(BaseModel):
    conversation_id: str
    title: str | None = None
    updated_at: datetime
    execution_id: str
    host_turn_id: str
    acts: list[CollaborationTimelineAct] = Field(default_factory=list)
    dossier_refs: list[CollaborationDossierRef] = Field(default_factory=list)


class CollaborationTimelineResponse(BaseModel):
    folder_id: str
    items: list[CollaborationTimelineItem] = Field(default_factory=list)
    total: int = 0
    limit: int = 20
    offset: int = 0
    dossier_refs_note: str = (
        "路径级案卷消费事实（本场辩论开赛注入或会话内 file_read），非跨会话过程边"
    )
