"""节目 API：期列表 / manifest / 竞猜提交与结算 / 发布态门禁。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from agentcore.api.dependencies import AuthUser
from agentcore.api.schemas.show import (
    PatchShowEpisodePublishRequest,
    ShowEpisodeListResponse,
    ShowEpisodeSummary,
    ShowManifestResponse,
    ShowQuizSettlementResponse,
    SubmitShowQuizRequest,
)
from agentcore.core.errors import AuthorizationError, NotFoundError, ValidationError
from agentcore.simulation.service import simulation_enabled
from agentcore.simulation.show.catalog import (
    get_manifest,
    get_meta,
    list_episodes,
    set_publish_status,
    submit_quiz,
)
from agentcore.simulation.show.models import QuizSubmission

router = APIRouter(prefix="/simulation/show", tags=["simulation-show"])


def _require_simulation_enabled() -> None:
    if not simulation_enabled():
        raise NotFoundError("模拟功能未启用")


@router.get("/seasons/{season_id}/episodes", response_model=ShowEpisodeListResponse)
async def list_season_episodes(
    season_id: str,
    user: AuthUser,
    include_unpublished: bool = Query(False),
):
    _require_simulation_enabled()
    rows = list_episodes(season_id)
    if not include_unpublished:
        rows = [r for r in rows if r.publish_status == "published"]
    data = [ShowEpisodeSummary.model_validate(r.model_dump()) for r in rows]
    return ShowEpisodeListResponse(data=data, total=len(data))


@router.get("/episodes/{episode_id}/manifest", response_model=ShowManifestResponse)
async def get_episode_manifest(
    episode_id: str,
    user: AuthUser,
    preview: bool = Query(False, description="草稿预览（跳过发布门禁）"),
):
    _require_simulation_enabled()
    meta = get_meta(episode_id)
    if meta is None:
        raise NotFoundError("期不存在")
    if not preview and meta.publish_status != "published":
        raise AuthorizationError("该期尚未发布")
    manifest = get_manifest(episode_id, require_published=False)
    if manifest is None:
        raise NotFoundError("manifest 不存在")
    return ShowManifestResponse(manifest=manifest.model_dump(mode="json", by_alias=True))


@router.post(
    "/episodes/{episode_id}/quiz",
    response_model=ShowQuizSettlementResponse,
)
async def post_episode_quiz(
    episode_id: str,
    body: SubmitShowQuizRequest,
    user: AuthUser,
):
    _require_simulation_enabled()
    meta = get_meta(episode_id)
    if meta is None:
        raise NotFoundError("期不存在")
    if meta.publish_status not in ("published", "review"):
        raise AuthorizationError("该期未开放竞猜")
    try:
        settlement = submit_quiz(
            QuizSubmission(
                episode_id=episode_id,
                user_id=user.user_id,
                guess=body.guess,
            )
        )
    except KeyError as exc:
        raise NotFoundError("期不存在") from exc
    return ShowQuizSettlementResponse.model_validate(settlement.model_dump())


@router.patch("/episodes/{episode_id}/publish", response_model=ShowEpisodeSummary)
async def patch_episode_publish(
    episode_id: str,
    body: PatchShowEpisodePublishRequest,
    user: AuthUser,
):
    """发布态门禁位（draft → review → published）。生产环境应再加 admin 鉴权。"""
    _require_simulation_enabled()
    try:
        meta = set_publish_status(episode_id, body.publish_status)
    except KeyError as exc:
        raise NotFoundError("期不存在") from exc
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return ShowEpisodeSummary.model_validate(meta.model_dump())
