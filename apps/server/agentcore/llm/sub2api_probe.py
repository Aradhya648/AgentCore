"""Best-effort Sub2API admin probe for 503 upstream diagnostics."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from agentcore.config.settings import settings
from agentcore.core.logging import get_logger
from agentcore.core.net import outbound_async_client

logger = get_logger(__name__)

_PROBE_TIMEOUT = 3.0
_DEFAULT_TOKEN_TTL = 360.0

_cached_token: str | None = None
_token_expires_at: float = 0.0


@dataclass(frozen=True)
class Sub2ApiProbeResult:
    diagnosis: str
    account_email_masked: str | None


def _mask_email(email: str) -> str:
    if "@" not in email:
        return email[:3] + "***" if len(email) > 3 else "***"
    local, domain = email.split("@", 1)
    prefix = local[:3] if len(local) >= 3 else local
    return f"{prefix}***@{domain}"


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def _format_time(dt: datetime) -> str:
    local = dt.astimezone()
    return local.strftime("%H:%M")


def _account_email(account: dict[str, Any]) -> str:
    credentials = account.get("credentials") or {}
    return (
        credentials.get("email")
        or account.get("email")
        or account.get("name")
        or "unknown"
    )


def _diagnose_account(account: dict[str, Any]) -> Sub2ApiProbeResult:
    email = _account_email(account)
    masked = _mask_email(email)
    credentials = account.get("credentials") or {}
    extra = account.get("extra") or {}
    credentials_status = account.get("credentials_status") or {}

    expires_at = _parse_time(credentials.get("expires_at") or account.get("expires_at"))
    now = datetime.now(UTC)
    if expires_at is not None and expires_at <= now:
        return Sub2ApiProbeResult(
            diagnosis=f"OAuth token 已过期（到期时间 {_format_time(expires_at)}），需要重新登录 ChatGPT",
            account_email_masked=masked,
        )

    reset_at = _parse_time(extra.get("codex_5h_reset_at"))
    if reset_at is not None and reset_at > now:
        return Sub2ApiProbeResult(
            diagnosis=f"5 小时使用配额已用完，将在 {_format_time(reset_at)} 重置",
            account_email_masked=masked,
        )

    if credentials_status.get("has_access_token") is False:
        return Sub2ApiProbeResult(
            diagnosis="账号未绑定 access token",
            account_email_masked=masked,
        )

    return Sub2ApiProbeResult(
        diagnosis=f"账号 {email} token 有效但被上游拒绝，可能被限流或暂停",
        account_email_masked=masked,
    )


def _is_upstream_rejection(diagnosis: str) -> bool:
    return "token 有效但被上游拒绝" in diagnosis


def _extract_accounts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        items = data.get("items", data.get("list"))
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


async def _login_admin(client: httpx.AsyncClient) -> str | None:
    global _cached_token, _token_expires_at

    if _cached_token and time.monotonic() < _token_expires_at:
        return _cached_token

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": settings.sub2api_admin_email,
            "password": settings.sub2api_admin_password,
        },
    )
    response.raise_for_status()
    body = response.json()
    token = (
        body.get("data", {}).get("access_token")
        or body.get("access_token")
        or body.get("token")
    )
    if not token:
        return None

    expires_in = body.get("data", {}).get("expires_in") or body.get("expires_in")
    ttl = float(expires_in) if expires_in else _DEFAULT_TOKEN_TTL
    _cached_token = token
    _token_expires_at = time.monotonic() + max(ttl - 30.0, 60.0)
    return token


async def _probe_sub2api() -> Sub2ApiProbeResult | None:
    if not settings.sub2api_admin_url:
        return None

    async with outbound_async_client(
        base_url=settings.sub2api_admin_url.rstrip("/"),
        timeout=httpx.Timeout(_PROBE_TIMEOUT),
    ) as client:
        token = await _login_admin(client)
        if not token:
            logger.warning("llm.sub2api_probe_failed", reason="missing_admin_token")
            return None

        response = await client.get(
            "/api/v1/admin/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        accounts = _extract_accounts(response.json())
        if not accounts:
            logger.warning("llm.sub2api_probe_failed", reason="no_accounts")
            return None

        fallback: Sub2ApiProbeResult | None = None
        for account in accounts:
            result = _diagnose_account(account)
            if fallback is None:
                fallback = result
            if not _is_upstream_rejection(result.diagnosis):
                logger.info(
                    "llm.sub2api_probe",
                    account=result.account_email_masked,
                    diagnosis=result.diagnosis,
                )
                return result

        if fallback is None:
            return None
        logger.info(
            "llm.sub2api_probe",
            account=fallback.account_email_masked,
            diagnosis=fallback.diagnosis,
        )
        return fallback


async def probe_sub2api_diagnosis() -> str | None:
    """503 时调用，探测 Sub2API 管理 API 获取账号状态。

    返回中文诊断描述，失败返回 None。
    """
    try:
        result = await _probe_sub2api()
    except Exception as exc:
        logger.warning("llm.sub2api_probe_failed", reason=str(exc))
        return None
    return result.diagnosis if result else None


async def probe_sub2api_diagnosis_result() -> Sub2ApiProbeResult | None:
    """Like :func:`probe_sub2api_diagnosis` but also returns the masked account email."""
    try:
        return await _probe_sub2api()
    except Exception as exc:
        logger.warning("llm.sub2api_probe_failed", reason=str(exc))
        return None
