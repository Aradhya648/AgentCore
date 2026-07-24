"""SQLAlchemy base configuration and session management.

Two pools share one Postgres URL but separate budgets (as-built: 成本配额 §三):

* ``engine`` / ``async_session_factory`` — **primary** (content-write priority):
  request sessions, turn finalize, content checkpoints, and other authoritative
  conversation writes.
* ``telemetry_engine`` / ``telemetry_session_factory`` — **telemetry**:
  proxy_spend ledger drain, journal append-on-emit, audit, session roster.
  Sized smaller so a debate-storm of telemetry writes cannot exhaust the
  primary pool and starve message persistence.
"""

import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from agentcore.config import settings
from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# A readiness probe must fail fast: a refused connection errors instantly, but a
# dropped / firewalled host would otherwise hang until the driver timeout.
_DB_PROBE_TIMEOUT_S = 3.0


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


def _build_engine(*, pool_size: int, max_overflow: int, pool_timeout: int):
    return create_async_engine(
        settings.database_url,
        # SQL echo is governed by its own switch (NOT `debug`) so DEBUG app logs don't
        # drown the AI turn logs under every statement + parameters (see config.py).
        echo=settings.db_echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        # Pooled connections die out-of-band (PG idle timeout, NAT/firewall drop, laptop
        # sleep, DB restart): a stale checkout then raises asyncpg "connection is closed"
        # as a one-off 500. pre_ping validates liveness before each use and transparently
        # swaps in a fresh connection; recycle proactively retires connections older than
        # 30 min so they're replaced before the server's idle timeout can drop them.
        pool_pre_ping=True,
        pool_recycle=1800,
    )


engine = _build_engine(
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
)

telemetry_engine = _build_engine(
    pool_size=settings.db_telemetry_pool_size,
    max_overflow=settings.db_telemetry_max_overflow,
    pool_timeout=settings.db_telemetry_pool_timeout,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

telemetry_session_factory = async_sessionmaker(
    telemetry_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async DB session from the primary pool."""
    async with async_session_factory() as session:
        yield session


async def database_ready(timeout_s: float = _DB_PROBE_TIMEOUT_S) -> bool:
    """True iff a trivial query round-trips within ``timeout_s``.

    The single source for「is PostgreSQL reachable right now?」— used by the
    Kubernetes readiness probe (``/readyz``) and the admin system panel
    (管理员后台 P2 系统状态). A pure probe on a fresh session: it swallows every
    error (returning False, logged once) so each caller decides how to react
    (a ``503`` vs. a read-only status flag).
    """
    try:
        async with async_session_factory() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout_s)
        return True
    except Exception:  # noqa: BLE001 - any failure means "not ready"; reason logged
        logger.warning("db.ping_failed", exc_info=True)
        return False
