"""Admin feedback management routes (管理员反馈管理).

- ``GET   /v1/admin/feedback``            list all feedback
- ``PATCH /v1/admin/feedback/{id}/status`` update feedback status
"""

from fastapi import APIRouter, Depends, HTTPException

from agentcore.api.dependencies import AdminUser, get_feedback_repo, get_user_repo
from agentcore.api.schemas import (
    AdminFeedbackSummary,
    FeedbackListResponse,
    FeedbackSummary,
    UpdateFeedbackStatusRequest,
)
from agentcore.db.repositories.feedback import FeedbackRepository
from agentcore.db.repositories.users import UserRepository

router = APIRouter()


@router.get("/feedback", response_model=FeedbackListResponse)
async def list_all_feedback(
    _admin: AdminUser,
    status: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
    repo: FeedbackRepository = Depends(get_feedback_repo),
    user_repo: UserRepository = Depends(get_user_repo),
):
    """Admin: list all user feedback, optionally filtered."""
    data, total = await repo.list_all(
        status=status, category=category, limit=limit, offset=offset
    )
    items: list[FeedbackSummary] = []
    for row in data:
        user = await user_repo.get_by_id(row.user_id)
        items.append(
            AdminFeedbackSummary(
                id=row.id,
                user_id=row.user_id,
                user_display_name=user.display_name if user else None,
                category=row.category,
                title=row.title,
                description=row.description,
                page_context=row.page_context,
                status=row.status,
                admin_reply=row.admin_reply,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return FeedbackListResponse(data=items, total=total)


@router.patch("/feedback/{feedback_id}/status", response_model=FeedbackSummary)
async def update_feedback_status(
    feedback_id: str,
    body: UpdateFeedbackStatusRequest,
    _admin: AdminUser,
    repo: FeedbackRepository = Depends(get_feedback_repo),
):
    """Admin: update a feedback item's status and optionally reply."""
    row = await repo.update_status(
        feedback_id, status=body.status, admin_reply=body.admin_reply
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
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
