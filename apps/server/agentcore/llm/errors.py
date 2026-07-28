"""LLM error context helpers — unified upstream diagnostics."""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from agentcore.core.errors import AgentCoreError, LLMError, LLMUpstreamError

_BODY_PREVIEW_MAX = 500


class EmptyResponseDiagnosis(StrEnum):
    OAUTH_EXPIRED = "oauth_expired"
    CONTENT_FILTERED = "content_filtered"
    MODEL_UNKNOWN = "model_unknown"
    SILENT_EMPTY = "silent_empty"
    FORMAT_MISMATCH = "format_mismatch"


_OAUTH_MARKERS = re.compile(
    r"(<html|</html>|<!doctype|oauth|sign[\s_-]?in|login|unauthorized|access[\s_-]?denied)",
    re.IGNORECASE,
)
_MODEL_UNKNOWN_MARKERS = re.compile(
    r"(model[\s_-]?(not[\s_-]?found|does[\s_-]?not[\s_-]?exist|unknown|invalid)|"
    r"unknown[\s_-]?model|invalid[\s_-]?model)",
    re.IGNORECASE,
)

_DIAGNOSIS_LABELS: dict[EmptyResponseDiagnosis, str] = {
    EmptyResponseDiagnosis.OAUTH_EXPIRED: "模型无响应 · 可能需要刷新 Sub2API OAuth",
    EmptyResponseDiagnosis.CONTENT_FILTERED: "内容被过滤",
    EmptyResponseDiagnosis.MODEL_UNKNOWN: "模型名未被上游识别",
    EmptyResponseDiagnosis.SILENT_EMPTY: "模型返回空内容",
    EmptyResponseDiagnosis.FORMAT_MISMATCH: "上游响应格式异常",
}


def diagnose_empty_response(
    *,
    raw_body: str | None,
    finish_reason: str | None = None,
    format_mismatch: bool = False,
) -> EmptyResponseDiagnosis:
    """Classify an empty LLM response from upstream body / finish_reason."""
    if format_mismatch:
        return EmptyResponseDiagnosis.FORMAT_MISMATCH
    if finish_reason == "content_filter":
        return EmptyResponseDiagnosis.CONTENT_FILTERED
    text = (raw_body or "").strip()
    if text and _OAUTH_MARKERS.search(text):
        return EmptyResponseDiagnosis.OAUTH_EXPIRED
    if text and _MODEL_UNKNOWN_MARKERS.search(text):
        return EmptyResponseDiagnosis.MODEL_UNKNOWN
    if text:
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("error"):
                err = data["error"]
                err_text = err if isinstance(err, str) else json.dumps(err, ensure_ascii=False)
                if _OAUTH_MARKERS.search(err_text):
                    return EmptyResponseDiagnosis.OAUTH_EXPIRED
                if _MODEL_UNKNOWN_MARKERS.search(err_text):
                    return EmptyResponseDiagnosis.MODEL_UNKNOWN
        except json.JSONDecodeError:
            if "<" in text and ">" in text:
                return EmptyResponseDiagnosis.OAUTH_EXPIRED
            # A non-JSON ``text`` here is the streaming SSE tail (several ``data:``
            # lines), NOT a real format error — the genuine "couldn't parse any
            # chunk" case is signalled up front by the explicit ``format_mismatch``
            # flag. Fall through to SILENT_EMPTY so a clean tool_calls/stop finish
            # with empty deltas reads as "模型返回空内容" instead of the misleading
            # "上游响应格式异常".
    return EmptyResponseDiagnosis.SILENT_EMPTY


def empty_response_event_message(diagnosis: str | EmptyResponseDiagnosis | None) -> str:
    """User-facing SSE error message for a degraded empty-response finish."""
    base = "模型多次空响应"
    if diagnosis is None:
        return base
    try:
        key = EmptyResponseDiagnosis(diagnosis)
    except ValueError:
        return f"{base} · {diagnosis}"
    label = _DIAGNOSIS_LABELS.get(key)
    return f"{base} · {label}" if label else base


def empty_response_chip_label(diagnosis: str | EmptyResponseDiagnosis | None) -> str | None:
    """Short label for the degraded finish-reason chip (diagnosis only)."""
    if diagnosis is None:
        return None
    try:
        key = EmptyResponseDiagnosis(diagnosis)
    except ValueError:
        return str(diagnosis)
    return _DIAGNOSIS_LABELS.get(key)


@dataclass(frozen=True)
class LLMErrorContext:
    upstream_status: int
    upstream_body_preview: str | None
    retry_attempts: int


def body_preview(raw: bytes | str | None) -> str | None:
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.strip()
    if not text:
        return None
    if len(text) > _BODY_PREVIEW_MAX:
        return text[:_BODY_PREVIEW_MAX] + "…"
    return text


def _extract_upstream_message(preview: str | None) -> str | None:
    if not preview:
        return None
    try:
        data = json.loads(preview)
    except json.JSONDecodeError:
        return preview if len(preview) <= 200 else preview[:200] + "…"
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        if msg:
            return str(msg)
    if isinstance(err, str):
        return err
    msg = data.get("message")
    return str(msg) if msg else None


def _extract_upstream_code(preview: str | None) -> str | None:
    if not preview:
        return None
    try:
        data = json.loads(preview)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, dict):
        code = err.get("code")
        return str(code) if code else None
    return None


_AUTH_BODY_CODES = frozenset(
    {
        "key_expired",
        "invalid_api_key",
        "authentication_error",
        "invalid_api_token",
        "account_deactivated",
    }
)
_AUTH_BODY_MARKERS = re.compile(
    r"(api[\s_-]?key|access[\s_-]?token|unauthorized|authentication|"
    r"key[\s_-]?expired|expired|鉴权|无效.*key|key.*无效)",
    re.IGNORECASE,
)


def is_auth_rejection(status_code: int, body: bytes | str | None) -> bool:
    """True when a 401/403 should surface as key/auth failure (not model-not-allowed)."""
    if status_code == 401:
        return True
    if status_code != 403:
        return False
    preview = body_preview(body)
    code = (_extract_upstream_code(preview) or "").lower()
    if code in _AUTH_BODY_CODES:
        return True
    # Explicit non-auth 403s (model allowlist, etc.) stay as generic client errors.
    if code in {"model_not_allowed", "model_not_found", "insufficient_quota"}:
        return False
    extracted = _extract_upstream_message(preview) or ""
    return bool(_AUTH_BODY_MARKERS.search(extracted))


def client_error_message(
    provider_name: str, status_code: int, body: bytes | str | None
) -> str:
    extracted = _extract_upstream_message(body_preview(body))
    if extracted:
        return f"{provider_name} {extracted}"
    if status_code == 400:
        return f"{provider_name} 请求格式被拒绝（400），请检查模型与参数配置"
    if status_code == 404:
        return f"{provider_name} 接口地址不可达（404），请检查 base_url 配置"
    return f"{provider_name} 请求被拒绝（{status_code}），请稍后再试"


def upstream_client_error(
    message: str,
    *,
    status: int,
    body: bytes | str | None = None,
) -> LLMError:
    return LLMError(
        message,
        upstream_status=status,
        upstream_body_preview=body_preview(body),
    )


def upstream_error(
    message: str,
    *,
    status: int,
    body: bytes | str | None = None,
    retry_attempts: int = 0,
) -> LLMUpstreamError:
    ctx = LLMErrorContext(
        upstream_status=status,
        upstream_body_preview=body_preview(body),
        retry_attempts=retry_attempts,
    )
    return LLMUpstreamError(
        message,
        upstream_status=ctx.upstream_status,
        upstream_body_preview=ctx.upstream_body_preview,
        retry_attempts=ctx.retry_attempts,
    )


def is_retryable_upstream_status(status: int) -> bool:
    """5xx upstream failures are transient; 4xx client errors are not."""
    return status >= 500


def is_non_retryable_client_status(status: int) -> bool:
    """Explicit client/auth/balance failures — never retry."""
    return status in (400, 401, 402, 403)


def error_context_from(exc: BaseException) -> dict[str, int | str | float | None] | None:
    """Extract LLM upstream context for SSE / API payloads."""
    if not isinstance(exc, AgentCoreError):
        return None
    from agentcore.core.errors import LLMRateLimitError

    status = exc.details.get("upstream_status")
    retry_after = exc.details.get("retry_after")
    if isinstance(exc, LLMRateLimitError) and retry_after is None:
        retry_after = getattr(exc, "retry_after", None)

    if status is None and retry_after is None and not isinstance(exc, LLMRateLimitError):
        return None

    ctx: dict[str, int | str | float | None] = {}
    if status is not None:
        ctx["upstream_status"] = status
        ctx["upstream_body_preview"] = exc.details.get("upstream_body_preview")
        ctx["retry_attempts"] = exc.details.get("retry_attempts", 0)
    if retry_after is not None:
        with contextlib.suppress(TypeError, ValueError):
            ctx["retry_after"] = float(retry_after)
    if exc.details.get("sub2api_diagnosis"):
        ctx["sub2api_diagnosis"] = exc.details["sub2api_diagnosis"]
    if exc.details.get("sub2api_account"):
        ctx["sub2api_account"] = exc.details["sub2api_account"]
    return ctx or None
