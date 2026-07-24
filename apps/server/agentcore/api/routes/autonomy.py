"""User autonomy-policy preference — seeds new-conversation PermissionPreset only."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from agentcore.api.dependencies import AuthUser, get_user_repo
from agentcore.core.types import AutonomyPolicy
from agentcore.db.repositories import UserRepository

router = APIRouter(prefix="/users/me/autonomy", tags=["autonomy"])


class AutonomyView(BaseModel):
    policy: AutonomyPolicy = AutonomyPolicy.FIRST_GRANT


class AutonomyUpdate(BaseModel):
    policy: AutonomyPolicy = Field(
        ...,
        description=(
            "New-session default: always_ask→observe | first_grant→workspace | "
            "full_auto→full_trust"
        ),
    )

@router.get("", response_model=AutonomyView)
async def get_autonomy(
    user: AuthUser,
    users: UserRepository = Depends(get_user_repo),
) -> AutonomyView:
    row = await users.get_by_id(user.user_id)
    raw = (row.autonomy_policy if row else None) or AutonomyPolicy.FIRST_GRANT.value
    try:
        return AutonomyView(policy=AutonomyPolicy(raw))
    except ValueError:
        return AutonomyView(policy=AutonomyPolicy.FIRST_GRANT)


@router.put("", response_model=AutonomyView)
async def put_autonomy(
    body: AutonomyUpdate,
    user: AuthUser,
    users: UserRepository = Depends(get_user_repo),
) -> AutonomyView:
    await users.set_autonomy_policy(user.user_id, body.policy.value)
    return AutonomyView(policy=body.policy)
