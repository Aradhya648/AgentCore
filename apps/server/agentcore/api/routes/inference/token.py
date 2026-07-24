"""Inference token mint and bearer auth for the sidecar proxy."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_db, get_user_repo
from agentcore.config import settings
from agentcore.conversation.inference_rate_limit import enforce_inference_token_mint_rate_limit
from agentcore.core.errors import AuthenticationError
from agentcore.db.models import User
from agentcore.db.repositories import UserRepository
from agentcore.llm.resolve import resolve_user_chat_model
from agentcore.security.tokens import create_inference_token, decode_inference_token

router = APIRouter()


class InferenceTokenResponse(BaseModel):
    """A freshly minted inference token + its lifetime + server-resolved upstream model."""

    token: str
    expires_in_sec: int
    model: str


@router.post("/inference/token", response_model=InferenceTokenResponse)
async def mint_inference_token(
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
) -> InferenceTokenResponse:
    """Exchange the caller's cookie session for a scoped inference token."""
    await enforce_inference_token_mint_rate_limit(user.user_id)
    model = await resolve_user_chat_model(session, user.user_id)
    return InferenceTokenResponse(
        token=create_inference_token(user.user_id),
        expires_in_sec=settings.inference_token_expire_minutes * 60,
        model=model,
    )


async def inference_user(
    authorization: Annotated[str | None, Header()] = None,
    user_repo: UserRepository = Depends(get_user_repo),
) -> User:
    """Resolve the user from ``Authorization: Bearer <inference-token>``."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("Missing inference token")
    user_id = decode_inference_token(authorization.split(" ", 1)[1].strip())
    user = await user_repo.get_by_id(user_id)
    if user is None or user.status != "active":
        raise AuthenticationError("User not found or inactive")
    return user
