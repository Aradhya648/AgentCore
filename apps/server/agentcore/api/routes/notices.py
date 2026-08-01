"""User-facing product notice routes (全局 Notice).

- ``GET  /v1/notices/active``          banner + modal + inbox for current user
- ``POST /v1/notices/{id}/dismiss``    dismiss (once); never → 409; idempotent
"""

from fastapi import APIRouter, Depends, HTTPException, Response

from agentcore.api.dependencies import AuthUser, get_notice_repo
from agentcore.api.schemas import ActiveNotice, ActiveNoticesResponse
from agentcore.db.repositories.notices import ProductNoticeRepository

router = APIRouter(prefix="/notices", tags=["notices"])


def _active(row, *, dismissed: bool) -> ActiveNotice:
    return ActiveNotice(
        id=row.id,
        title=row.title,
        body=row.body,
        severity=row.severity,
        surface=row.surface,
        dismiss_policy=row.dismiss_policy,
        cta_label=row.cta_label,
        cta_url=row.cta_url,
        published_at=row.published_at,
        dismissed=dismissed,
    )


@router.get("/active", response_model=ActiveNoticesResponse)
async def get_active_notices(
    user: AuthUser,
    repo: ProductNoticeRepository = Depends(get_notice_repo),
):
    """Return banner (≤1), modal (≤1, undismissed), and inbox for the signed-in user.

    Priority: ``critical`` banner > undismissed modal > non-critical banner.
    When an undismissed modal is present and the banner candidate is not
    ``critical``, ``banner`` is omitted.
    """
    rows = await repo.list_active_published()
    dismissed_ids = await repo.list_dismissed_ids(user.user_id, [r.id for r in rows])

    banner: ActiveNotice | None = None
    modal: ActiveNotice | None = None
    inbox: list[ActiveNotice] = []
    for row in rows:
        dismissed = row.id in dismissed_ids
        # once+dismissed → hide from banner; never stays visible even if dismissed.
        if (
            banner is None
            and row.surface in ("banner", "both")
            and (not dismissed or row.dismiss_policy == "never")
        ):
            banner = _active(row, dismissed=dismissed)
        # modal: only undismissed (policy is always once); ≤1 via sort order.
        if modal is None and row.surface == "modal" and not dismissed:
            modal = _active(row, dismissed=False)
        if row.surface in ("inbox", "both", "modal"):
            inbox.append(_active(row, dismissed=dismissed))

    # critical > modal > normal/high banner
    if modal is not None and banner is not None and banner.severity != "critical":
        banner = None

    return ActiveNoticesResponse(banner=banner, modal=modal, inbox=inbox)


@router.post("/{notice_id}/dismiss", status_code=204)
async def dismiss_notice(
    notice_id: str,
    user: AuthUser,
    repo: ProductNoticeRepository = Depends(get_notice_repo),
):
    """Dismiss a notice (``once``). ``never`` → 409; already dismissed → 204."""
    row = await repo.get(notice_id)
    if row is None or row.status != "published":
        raise HTTPException(status_code=404, detail="Notice not found")
    if row.dismiss_policy == "never":
        raise HTTPException(status_code=409, detail="This notice cannot be dismissed")
    await repo.dismiss(notice_id, user.user_id)
    return Response(status_code=204)
