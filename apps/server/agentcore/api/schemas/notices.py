"""Product notice schemas (全局 Notice)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "normal"]
Surface = Literal["banner", "inbox", "both", "modal"]
NoticeStatus = Literal["draft", "published", "archived"]
DismissPolicy = Literal["once", "never"]


class CreateNoticeRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    severity: Severity = "normal"
    surface: Surface = "both"
    dismiss_policy: DismissPolicy = "once"
    cta_label: str | None = Field(None, max_length=100)
    cta_url: str | None = Field(None, max_length=2000)
    start_at: datetime | None = None
    end_at: datetime | None = None


class UpdateNoticeRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    body: str | None = Field(None, min_length=1)
    severity: Severity | None = None
    surface: Surface | None = None
    dismiss_policy: DismissPolicy | None = None
    cta_label: str | None = Field(None, max_length=100)
    cta_url: str | None = Field(None, max_length=2000)
    start_at: datetime | None = None
    end_at: datetime | None = None


class NoticeSummary(BaseModel):
    id: str
    title: str
    body: str
    severity: str
    surface: str
    status: str
    dismiss_policy: str
    cta_label: str | None
    cta_url: str | None
    start_at: datetime | None
    end_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class NoticeListResponse(BaseModel):
    data: list[NoticeSummary]
    total: int


class ActiveNotice(BaseModel):
    id: str
    title: str
    body: str
    severity: str
    surface: str
    dismiss_policy: str
    cta_label: str | None
    cta_url: str | None
    published_at: datetime | None
    dismissed: bool


class ActiveNoticesResponse(BaseModel):
    banner: ActiveNotice | None
    modal: ActiveNotice | None
    inbox: list[ActiveNotice]
