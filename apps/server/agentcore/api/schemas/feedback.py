"""User feedback schemas (内测反馈)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CreateFeedbackRequest(BaseModel):
    category: Literal["bug", "feature", "improvement", "other"]
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    page_context: str | None = Field(None, max_length=500)


class FeedbackSummary(BaseModel):
    id: str
    category: str
    title: str
    description: str
    page_context: str | None
    status: str
    admin_reply: str | None
    created_at: datetime
    updated_at: datetime


class FeedbackListResponse(BaseModel):
    data: list[FeedbackSummary]
    total: int


class UpdateFeedbackStatusRequest(BaseModel):
    status: Literal["open", "acknowledged", "resolved", "closed"]
    admin_reply: str | None = Field(None, max_length=2000)


class AdminFeedbackSummary(FeedbackSummary):
    user_id: str
    user_display_name: str | None = None
