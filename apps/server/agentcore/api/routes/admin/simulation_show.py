"""Admin: simulation show publish gate（恋综节目发布态）。

Product 路由上的 AdminUser 会被 audience 隔离拦下（admin 会话只能打
``/v1/admin/*``），故发布写接口挂在管理后台前缀下，与其它 admin 路由一致。
"""

from __future__ import annotations

from fastapi import APIRouter

from agentcore.api.dependencies import AdminUser
from agentcore.api.schemas.show import PatchShowEpisodePublishRequest, ShowEpisodeSummary
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.simulation.service import simulation_enabled
from agentcore.simulation.show.catalog import set_publish_status

router = APIRouter()


def _require_simulation_enabled() -> None:
    if not simulation_enabled():
        raise NotFoundError("模拟功能未启用")


@router.patch(
    "/simulation/show/episodes/{episode_id}/publish",
    response_model=ShowEpisodeSummary,
)
async def patch_episode_publish(
    episode_id: str,
    body: PatchShowEpisodePublishRequest,
    _admin: AdminUser,
):
    """发布态门禁（draft → review → published）。仅管理后台 Admin。"""
    _require_simulation_enabled()
    try:
        meta = set_publish_status(episode_id, body.publish_status)
    except KeyError as exc:
        raise NotFoundError("期不存在") from exc
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return ShowEpisodeSummary.model_validate(meta.model_dump())
