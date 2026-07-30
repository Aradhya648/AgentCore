"""Admin product notice management routes (全局 Notice 管理).

- ``GET    /v1/admin/notices``              list (status filter + pagination)
- ``POST   /v1/admin/notices``              create (default draft, 201)
- ``PATCH  /v1/admin/notices/{id}``         update content/enums/window/CTA
- ``POST   /v1/admin/notices/{id}/publish`` publish
- ``POST   /v1/admin/notices/{id}/archive`` archive
"""

from fastapi import APIRouter, Depends, HTTPException

from agentcore.api.dependencies import AdminUser, get_notice_repo
from agentcore.api.schemas import (
    CreateNoticeRequest,
    NoticeListResponse,
    NoticeSummary,
    UpdateNoticeRequest,
)
from agentcore.db.repositories.notices import ProductNoticeRepository

router = APIRouter()


def _summary(row) -> NoticeSummary:
    return NoticeSummary(
        id=row.id,
        title=row.title,
        body=row.body,
        severity=row.severity,
        surface=row.surface,
        status=row.status,
        dismiss_policy=row.dismiss_policy,
        cta_label=row.cta_label,
        cta_url=row.cta_url,
        start_at=row.start_at,
        end_at=row.end_at,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
        published_at=row.published_at,
    )


@router.get("/notices", response_model=NoticeListResponse)
async def list_notices(
    _admin: AdminUser,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    repo: ProductNoticeRepository = Depends(get_notice_repo),
):
    """Admin: list product notices, optionally filtered by status."""
    data, total = await repo.list_all(status=status, limit=limit, offset=offset)
    return NoticeListResponse(data=[_summary(r) for r in data], total=total)


@router.post("/notices", response_model=NoticeSummary, status_code=201)
async def create_notice(
    body: CreateNoticeRequest,
    admin: AdminUser,
    repo: ProductNoticeRepository = Depends(get_notice_repo),
):
    """Admin: create a draft notice."""
    row = await repo.create(
        title=body.title,
        body=body.body,
        severity=body.severity,
        surface=body.surface,
        dismiss_policy=body.dismiss_policy,
        created_by=admin.user_id,
        cta_label=body.cta_label,
        cta_url=body.cta_url,
        start_at=body.start_at,
        end_at=body.end_at,
    )
    return _summary(row)


@router.patch("/notices/{notice_id}", response_model=NoticeSummary)
async def update_notice(
    notice_id: str,
    body: UpdateNoticeRequest,
    _admin: AdminUser,
    repo: ProductNoticeRepository = Depends(get_notice_repo),
):
    """Admin: update notice fields. Archived notices are immutable (409)."""
    existing = await repo.get(notice_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    if existing.status == "archived":
        raise HTTPException(status_code=409, detail="Archived notices cannot be updated")

    fields = body.model_fields_set
    row = await repo.update(
        notice_id,
        title=body.title if "title" in fields else None,
        body=body.body if "body" in fields else None,
        severity=body.severity if "severity" in fields else None,
        surface=body.surface if "surface" in fields else None,
        dismiss_policy=body.dismiss_policy if "dismiss_policy" in fields else None,
        cta_label=body.cta_label if "cta_label" in fields else ...,
        cta_url=body.cta_url if "cta_url" in fields else ...,
        start_at=body.start_at if "start_at" in fields else ...,
        end_at=body.end_at if "end_at" in fields else ...,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    return _summary(row)


@router.post("/notices/{notice_id}/publish", response_model=NoticeSummary)
async def publish_notice(
    notice_id: str,
    _admin: AdminUser,
    repo: ProductNoticeRepository = Depends(get_notice_repo),
):
    """Admin: publish a notice (sets published_at)."""
    existing = await repo.get(notice_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    if existing.status == "archived":
        raise HTTPException(status_code=409, detail="Archived notices cannot be published")
    row = await repo.publish(notice_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    return _summary(row)


@router.post("/notices/{notice_id}/archive", response_model=NoticeSummary)
async def archive_notice(
    notice_id: str,
    _admin: AdminUser,
    repo: ProductNoticeRepository = Depends(get_notice_repo),
):
    """Admin: archive a notice (removes from active surfaces)."""
    existing = await repo.get(notice_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    if existing.status == "archived":
        return _summary(existing)
    row = await repo.archive(notice_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    return _summary(row)
