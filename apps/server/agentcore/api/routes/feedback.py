"""User feedback routes (内测反馈).

- ``POST  /v1/feedback``  submit feedback
- ``GET   /v1/feedback``  list own feedback
"""

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import AuthUser, get_feedback_repo
from agentcore.api.schemas import (
    CreateFeedbackRequest,
    FeedbackListResponse,
    FeedbackSummary,
)
from agentcore.db.repositories.feedback import FeedbackRepository

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _summary(row) -> FeedbackSummary:
    return FeedbackSummary(
        id=row.id,
        category=row.category,
        title=row.title,
        description=row.description,
        page_context=row.page_context,
        status=row.status,
        admin_reply=row.admin_reply,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("", response_model=FeedbackSummary, status_code=201)
async def submit_feedback(
    body: CreateFeedbackRequest,
    user: AuthUser,
    repo: FeedbackRepository = Depends(get_feedback_repo),
):
    """Submit a feedback entry (bug, feature request, etc.)."""
    row = await repo.create(
        user_id=user.user_id,
        category=body.category,
        title=body.title,
        description=body.description,
        page_context=body.page_context,
    )
    return _summary(row)


@router.get("", response_model=FeedbackListResponse)
async def list_my_feedback(
    user: AuthUser,
    limit: int = 50,
    offset: int = 0,
    repo: FeedbackRepository = Depends(get_feedback_repo),
):
    """List the current user's feedback (newest-first)."""
    data, total = await repo.list_by_user(user.user_id, limit=limit, offset=offset)
    return FeedbackListResponse(data=[_summary(r) for r in data], total=total)
