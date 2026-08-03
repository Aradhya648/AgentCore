"""System routes: liveness/readiness probes and build provenance.

The probes follow the Kubernetes convention so an orchestrator / load balancer
acts on the right signal:

- ``GET /livez`` — *liveness*: is the process up and serving HTTP at all? It
  touches no external dependency, so a transient database outage never trips it
  into a restart loop. Always ``200``.
- ``GET /readyz`` — *readiness*: can the service actually handle requests right
  now? It exercises every hard dependency (currently PostgreSQL via the shared
  ``database_ready`` probe) and returns ``503`` when one is unreachable, so
  traffic is held back until recovery.
- ``GET /version`` — build provenance (semantic version + git SHA + build time)
  for traceability and instant rollback.
- ``GET /updates/policy`` — desktop auto-update remote circuit breaker + hard
  floor. The desktop updater polls it before each check;
  ``enabled: false`` is a kill switch for a bad release; ``min_desktop_version``
  is the hard floor (client forced-update gate + server ``CLIENT_TOO_OLD`` API
  gate). Unauthenticated and dependency-free like ``/version`` so outdated
  clients can still fetch policy pre-login; kill switch is **fail-open**.

The desktop client probes ``/readyz`` on startup to tell an infrastructure
outage (e.g. the database is down) apart from a normal unauthenticated state, so
it can show an actionable "service unavailable" screen instead of a login form
that would fail anyway.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from agentcore.cache.redis_health import redis_ready
from agentcore.config import settings
from agentcore.db.base import database_ready

router = APIRouter(tags=["system"])


class UpdatesPolicyResponse(BaseModel):
    """Desktop update policy: kill switch + hard minimum client version."""

    enabled: bool
    min_desktop_version: str | None = Field(
        default=None,
        description=(
            "Semver hard floor for desktop; null when unset "
            "(no forced-update gate / no CLIENT_TOO_OLD API gate)."
        ),
    )


@router.get("/livez")
async def liveness() -> dict[str, str]:
    """Liveness probe: the process is up. Deliberately checks no dependencies."""
    return {"status": "alive"}


@router.get("/readyz")
async def readiness(response: Response) -> dict[str, object]:
    """Readiness probe: 200 when every hard dependency is reachable, else 503."""
    db_ok = await database_ready()
    redis_ok = await redis_ready()
    ready = db_ok and redis_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    body: dict[str, object] = {
        "status": "ready" if ready else "not_ready",
        "database": db_ok,
    }
    if settings.rate_limit_backend == "redis":
        body["redis"] = redis_ok
    return body


def app_version() -> str:
    """Semantic version from installed package metadata (single source: pyproject).

    Public so the admin system panel (管理员后台 P2) reports the same version the
    ``/version`` probe does — one provenance source.
    """
    try:
        return _package_version("agentcore")
    except PackageNotFoundError:  # running from a tree that was never installed
        return "unknown"


@router.get("/version")
async def version() -> dict[str, str]:
    """Build provenance for traceability: semantic version + git SHA + build time."""
    return {
        "version": app_version(),
        "git_sha": settings.git_sha,
        "built_at": settings.built_at,
    }


@router.get("/updates/policy", response_model=UpdatesPolicyResponse)
async def updates_policy() -> UpdatesPolicyResponse:
    """Desktop auto-update policy (发布与门禁.md §7.6).

    The desktop updater polls this before each check and pauses downloads when
    ``enabled`` is false — a kill switch for a bad release. ``min_desktop_version``
    is the hard floor: clients force update when older, and the server rejects
    ``X-Client-Platform=desktop`` business APIs below it with ``CLIENT_TOO_OLD``
    (HTTP 426). Empty ``DESKTOP_MIN_VERSION`` → ``min_desktop_version: null``
    (dev-friendly; no gate). This endpoint itself is exempt from the API gate so
    outdated clients can still learn the floor.

    Unauthenticated and dependency-free (like ``/version``) so the updater can
    reach it pre-login. The kill-switch client is **fail-open**: any error or
    non-200 is treated as enabled.

    Staged rollout (stagingPercentage) and beta/stable channels ride on the
    feature-flag system (发布与门禁.md §7.9) and are not part of this payload yet.
    Per-flag ``min_client_version`` (§7.9) remains a separate line from this
    global desktop floor.
    """
    raw = settings.desktop_min_version.strip()
    return UpdatesPolicyResponse(
        enabled=settings.desktop_updates_enabled,
        min_desktop_version=raw or None,
    )
