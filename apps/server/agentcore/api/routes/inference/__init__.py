"""Cloud inference proxy for the on-machine sidecar — token mint + LLM passthrough."""

from fastapi import APIRouter

from agentcore.api.routes.inference import proxy, token
from agentcore.config import settings
from agentcore.conversation.quota import QuotaLimits, enforce_quota
from agentcore.db.base import async_session_factory
from agentcore.db.repositories import CostEventRepository
from agentcore.llm.resolve import resolve_user_llm_credentials
from agentcore.runtime.costing import ROLE_CAPTAIN, background_run_cost
from agentcore.security.tokens import decode_inference_token

router = APIRouter(tags=["inference"])
router.include_router(token.router)
router.include_router(proxy.router)

# Stable import paths for tests and monkeypatch targets (see test_inference_proxy.py).
from agentcore.api.routes.inference.proxy import (  # noqa: E402
    _forward_stream,
    _forward_unary,
    _record_proxy_spend,
    _resolve_inference_credentials,
    usage_from_deepseek,
)
from agentcore.api.routes.inference.token import inference_user  # noqa: E402

__all__ = [
    "router",
    "settings",
    "decode_inference_token",
    "async_session_factory",
    "CostEventRepository",
    "resolve_user_llm_credentials",
    "enforce_quota",
    "QuotaLimits",
    "ROLE_CAPTAIN",
    "background_run_cost",
    "inference_user",
    "_resolve_inference_credentials",
    "usage_from_deepseek",
    "_record_proxy_spend",
    "_forward_unary",
    "_forward_stream",
]
