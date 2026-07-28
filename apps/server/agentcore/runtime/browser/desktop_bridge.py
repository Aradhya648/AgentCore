"""DesktopBrowserBridge client credentials + health (Local browser_* gate · C1/C4).

**Control plane (B-Arch):** Desktop re-sends ``browserBridge: {baseUrl, token}`` on
each sidecar ``initialize`` / ``startTurn`` / ``resume`` (same pattern as inference
tokens). Sidecar applies them via :func:`apply_desktop_bridge_from_turn`, which
clears the health cache so a prior failed probe cannot stick for the process life.

Legacy fallback: if no turn override has been applied yet, read
``AGENTCORE_BROWSER_BRIDGE_URL`` / ``AGENTCORE_BROWSER_BRIDGE_TOKEN`` from the
environment (dev probes / older spawners). Production desktop no longer relies on
spawn-time env alone.

``browser_execution_enabled_for`` (local backend) is True only when a probe of
``GET {url}/health`` with the Bearer token succeeds. Missing URL/token → not
enabled (tools withheld). A failed probe never silently falls back to gVisor (C4).

Tests inject via ``set_desktop_bridge_health_for_tests`` / ``apply_desktop_bridge_from_turn``.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# None = never probed this credential generation → local gate withholds until probe.
_desktop_bridge_healthy: bool | None = None

# Turn-level override (set by sidecar handlers). When ``_turn_override_active``,
# env is ignored for URL/token resolution.
_turn_override_active: bool = False
_turn_url: str | None = None
_turn_token: str | None = None


def desktop_bridge_url() -> str | None:
    if _turn_override_active:
        return _turn_url
    raw = (os.environ.get("AGENTCORE_BROWSER_BRIDGE_URL") or "").strip()
    return raw.rstrip("/") or None


def desktop_bridge_token() -> str | None:
    if _turn_override_active:
        return _turn_token
    raw = (os.environ.get("AGENTCORE_BROWSER_BRIDGE_TOKEN") or "").strip()
    return raw or None


def desktop_bridge_configured() -> bool:
    return bool(desktop_bridge_url() and desktop_bridge_token())


def desktop_bridge_health() -> bool | None:
    """Cached probe for the **current** credential generation: ``True`` / ``False`` / ``None``."""
    return _desktop_bridge_healthy


def reset_desktop_bridge_health_for_tests() -> None:
    global _desktop_bridge_healthy, _turn_override_active, _turn_url, _turn_token
    _desktop_bridge_healthy = None
    _turn_override_active = False
    _turn_url = None
    _turn_token = None


def set_desktop_bridge_health_for_tests(healthy: bool | None) -> None:
    """Inject a probe result for unit tests (``None`` = unprobed)."""
    global _desktop_bridge_healthy
    _desktop_bridge_healthy = healthy


def apply_desktop_bridge_from_turn(raw: Any) -> None:
    """Adopt per-turn ``browserBridge`` from desktop (mirrors inference refresh).

    - ``dict`` with ``baseUrl`` + ``token`` → override env; clear health cache; re-probe on demand.
    - ``None`` / missing keys / empty → override to unconfigured (withhold browser this turn).
    - Calling this always clears sticky health so a previous ``False`` cannot pin the process.
    """
    global _turn_override_active, _turn_url, _turn_token, _desktop_bridge_healthy
    _turn_override_active = True
    _desktop_bridge_healthy = None
    if not isinstance(raw, dict):
        _turn_url = None
        _turn_token = None
        logger.info("browser.desktop_bridge_turn_cleared")
        return
    url = str(raw.get("baseUrl") or "").strip().rstrip("/") or None
    token = str(raw.get("token") or "").strip() or None
    if not url or not token:
        _turn_url = None
        _turn_token = None
        logger.info("browser.desktop_bridge_turn_incomplete")
        return
    _turn_url = url
    _turn_token = token
    logger.info("browser.desktop_bridge_turn_applied", base_url=url)


def probe_desktop_bridge_sync(*, timeout_s: float = 1.5) -> bool:
    """Synchronous ``GET /health`` against the Desktop Bridge. Never raises."""
    global _desktop_bridge_healthy
    url = desktop_bridge_url()
    token = desktop_bridge_token()
    if not url or not token:
        _desktop_bridge_healthy = False if (url or token or _turn_override_active) else None
        return False

    req = Request(
        f"{url}/health",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 - loopback only
            body = resp.read().decode("utf-8", errors="replace")
            ok = resp.status == 200 and "desktop-browser-bridge" in body
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logger.info(
            "browser.desktop_bridge_probe_failed",
            reason=type(exc).__name__,
            detail=str(exc)[:200],
        )
        ok = False
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "browser.desktop_bridge_probe_error",
            reason=type(exc).__name__,
            detail=str(exc)[:200],
        )
        ok = False

    _desktop_bridge_healthy = ok
    return ok


def ensure_desktop_bridge_health(*, force: bool = False) -> bool:
    """Return whether the Bridge is healthy for **this credential generation**.

    Cached ``True`` is reused until :func:`apply_desktop_bridge_from_turn` resets it.
    Cached ``False`` / ``None`` re-probes when ``force`` or uncached — turn apply always
    clears to ``None``, so a failed probe cannot stick across turns (B-Arch-3).
    """
    if not force and _desktop_bridge_healthy is True:
        return True
    if not desktop_bridge_configured():
        return False
    if not force and _desktop_bridge_healthy is False:
        # Same credential generation already failed this turn — don't hammer loopback.
        return False
    return probe_desktop_bridge_sync()


def bridge_request_headers() -> dict[str, str]:
    token = desktop_bridge_token() or ""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def bridge_command_url() -> str:
    base = desktop_bridge_url()
    if not base:
        raise RuntimeError("host_unavailable: DesktopBrowserBridge URL 未配置")
    return f"{base}/command"


def parse_bridge_error(
    payload: dict[str, Any] | None, *, http_status: int
) -> tuple[str, str | None]:
    """Extract (error_message, code) from a Bridge error body."""
    if not payload:
        return f"bridge_http_{http_status}", "host_unavailable" if http_status >= 500 else None
    err = str(payload.get("error") or f"bridge_http_{http_status}")
    code = payload.get("code")
    code_s = str(code) if code else None
    if http_status == 503 or code_s == "host_unavailable" or "host_unavailable" in err:
        return err, "host_unavailable"
    return err, code_s
