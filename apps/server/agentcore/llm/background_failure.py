"""Classify side-path LLM failures for observability (title / followups / memory).

Buckets are product-chrome oriented: auth vs upstream blip vs timeout vs other.
Quota skips stay on ``billing.background_quota_skip`` — callers pass
``reason=quota_skip`` only when they already know the gate returned None after quota.
"""

from __future__ import annotations

from typing import Literal

from agentcore.core.errors import LLMAuthError, LLMTimeoutError, LLMUpstreamError

BackgroundFailureReason = Literal[
    "auth",
    "upstream_unstable",
    "timeout",
    "quota_skip",
    "provider_unavailable",
    "other",
]


def classify_background_llm_failure(exc: BaseException) -> BackgroundFailureReason:
    """Map an exception to a stable ``reason`` for side-path failure logs / SSE."""
    if isinstance(exc, LLMAuthError):
        return "auth"
    if isinstance(exc, TimeoutError | LLMTimeoutError):
        return "timeout"
    if isinstance(exc, LLMUpstreamError):
        status = _upstream_status(exc)
        if status is None or status >= 500:
            return "upstream_unstable"
        return "other"
    msg = str(exc).casefold()
    if "background credentials unavailable" in msg:
        return "provider_unavailable"
    if "quota" in msg or "free tier" in msg or "额度" in msg:
        return "quota_skip"
    return "other"


def _upstream_status(exc: LLMUpstreamError) -> int | None:
    details = getattr(exc, "details", None) or {}
    if not isinstance(details, dict):
        return None
    for key in ("upstream_status", "status", "status_code", "http_status"):
        raw = details.get(key)
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
    return None
