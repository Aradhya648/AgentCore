"""Process-level cloud sandbox availability (boot probe → capability gate).

One-shot at app lifespan when cloud execution is config-enabled. The cached
result folds into ``code_execution_enabled_for`` so worker registration and
``workspace_context`` stay aligned with real sandbox readiness. ``None``
(never probed) preserves config-only semantics for tests / local / unbooted.
"""

from __future__ import annotations

from agentcore.config import settings
from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# None = never probed → predicate keeps config-only semantics (status quo).
_cloud_sandbox_healthy: bool | None = None


def cloud_sandbox_health() -> bool | None:
    """Cached boot-probe result: ``True`` / ``False``, or ``None`` if never probed."""
    return _cloud_sandbox_healthy


def reset_cloud_sandbox_health_for_tests() -> None:
    """Clear the process-wide cache so tests cannot leak health across cases."""
    global _cloud_sandbox_healthy
    _cloud_sandbox_healthy = None


def set_cloud_sandbox_health_for_tests(healthy: bool | None) -> None:
    """Inject a probe result for unit tests (``None`` = unprobed)."""
    global _cloud_sandbox_healthy
    _cloud_sandbox_healthy = healthy


def cloud_execution_config_enabled() -> bool:
    """Whether config alone would allow server-side code execution."""
    return settings.gvisor_enabled or settings.code_execute_cloud_enabled


async def probe_cloud_sandbox_at_startup() -> None:
    """One-shot boot probe when cloud execution is config-enabled. Never raises.

    Uses the same default server sandbox as workspace construction. Missing
    ``health_check``, a false result, or any exception → unhealthy (tools withheld).
    """
    global _cloud_sandbox_healthy
    if not cloud_execution_config_enabled():
        return

    reason = "unhealthy"
    detail = ""
    try:
        from agentcore.workspace.locate import _default_server_sandbox

        sandbox = _default_server_sandbox()
        health_check = getattr(sandbox, "health_check", None)
        if health_check is None:
            ok = False
            reason = "missing_health_check"
        else:
            ok = bool(await health_check())
            if not ok:
                reason = "unhealthy"
    except Exception as exc:  # noqa: BLE001 — probe must never break startup
        ok = False
        reason = type(exc).__name__
        detail = str(exc)[:200]

    _cloud_sandbox_healthy = ok
    if ok:
        logger.debug("sandbox.cloud_health_ok")
        return

    logger.warning(
        "sandbox.cloud_health_failed",
        reason=reason,
        detail=detail or None,
        hint="云端 code_execute/test_run 将不装配，直到沙箱可用",
    )
