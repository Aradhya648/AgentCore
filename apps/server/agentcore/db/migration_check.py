"""Startup migration-drift check + optional auto-upgrade in debug.

Compares the database's applied Alembic revision against the migration scripts'
head(s). In **debug** (local/dev), attempts ``alembic upgrade head`` first so a
forgotten migration after parallel-worktree merges cannot leave the schema
behind — the classic footgun where another worktree adds a model column plus its
migration, but the local DB is never upgraded, so a query selecting the new
column 500s with ``UndefinedColumnError``.

In **production** (``settings.debug`` false) this is a *notice* only: it never
mutates schema, never raises, and never blocks startup. Auto-upgrade failures
in debug likewise never block startup — they fall through to the same drift
warnings so the signal still fires.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

import agentcore.db as _db_pkg
from agentcore.config import settings
from agentcore.core.logging import get_logger
from agentcore.db.base import engine

logger = get_logger(__name__)

_UPGRADE_HINT = "run `uv run alembic upgrade head` from apps/server"


def _alembic_config() -> Config:
    """Alembic Config without loading ``alembic.ini``.

    Avoids ``env.py``'s ``fileConfig(config_file_name)`` path, which would
    reconfigure the root logger and pollute the app's structured logging setup.
    ``env.py`` still overrides ``sqlalchemy.url`` from ``settings.database_url``.
    """
    migrations_dir = Path(_db_pkg.__file__).resolve().parent / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    return cfg


def _script_heads() -> set[str]:
    """Head revision(s) declared by the migration scripts (offline, reads files).

    Resolved from the package location rather than the cwd so the result is the
    same whether the server is launched from ``apps/server`` or elsewhere.
    """
    return set(ScriptDirectory.from_config(_alembic_config()).get_heads())


def _db_heads(sync_conn: Connection) -> set[str]:
    """Revision(s) recorded in the database's ``alembic_version`` table.

    Returns an empty set when the table is absent (a schema never put under
    Alembic management).
    """
    return set(MigrationContext.configure(sync_conn).get_current_heads())


def _upgrade_to_head() -> None:
    """Synchronous ``alembic upgrade head`` (must run off the asyncio loop).

    ``env.py`` calls ``asyncio.run(...)``, which is illegal inside a running
    event loop — callers must use ``asyncio.to_thread``.
    """
    command.upgrade(_alembic_config(), "head")


async def _auto_upgrade_dev() -> None:
    """Best-effort ``upgrade head`` when ``settings.debug``. Never raises.

    Already-at-head is a cheap no-op (revision compare only, no Alembic command).
    On any failure, returns quietly so the subsequent drift check still warns.
    """
    try:
        heads = _script_heads()
        async with engine.connect() as conn:
            before = await conn.run_sync(_db_heads)
    except Exception as exc:
        logger.warning(
            "db.migration_upgrade_failed",
            error=str(exc),
            phase="preflight",
            exc_info=True,
        )
        return

    if before == heads:
        logger.debug("db.migrations_upgrade_noop", heads=sorted(heads))
        return

    try:
        await asyncio.to_thread(_upgrade_to_head)
    except Exception as exc:
        logger.warning(
            "db.migration_upgrade_failed",
            error=str(exc),
            from_revisions=sorted(before),
            heads=sorted(heads),
            exc_info=True,
        )
        return

    try:
        async with engine.connect() as conn:
            after = await conn.run_sync(_db_heads)
    except Exception as exc:
        logger.warning(
            "db.migration_upgrade_failed",
            error=str(exc),
            phase="verify",
            from_revisions=sorted(before),
            exc_info=True,
        )
        return

    if before != after:
        logger.info(
            "db.migrations_upgraded",
            from_revisions=sorted(before),
            to_revisions=sorted(after),
        )
    else:
        # Upgrade reported success but revisions unchanged (e.g. race / no-op path).
        logger.debug("db.migrations_upgrade_noop", heads=sorted(after))


async def check_migrations() -> None:
    """Warn (never raise) when the DB schema diverges from the migration head.

    In debug, attempts an auto-upgrade first; production only reports drift.

    Surfaces three drift shapes:

    - DB behind / diverged from head — unapplied migration(s); the usual cause of
      ``UndefinedColumnError`` at runtime.
    - DB carries no Alembic version row — schema is not migration-managed.
    - Multiple script heads — branched migrations; ``upgrade head`` refuses until
      they are merged.
    """
    if settings.debug:
        await _auto_upgrade_dev()

    try:
        heads = _script_heads()
        async with engine.connect() as conn:
            current = await conn.run_sync(_db_heads)
    except Exception as exc:  # a flaky check must never break startup
        logger.warning("db.migration_check_failed", error=str(exc), exc_info=True)
        return

    if len(heads) > 1:
        logger.warning(
            "db.migrations_branched",
            heads=sorted(heads),
            detail="multiple migration heads — merge them before upgrading",
        )

    if not current:
        # Root-cause, persistent until someone migrates — error (not warning) so it
        # can't hide among routine startup noise. A schema-dependent background sweep
        # WILL fail every interval until this is resolved.
        logger.error(
            "db.migrations_unmanaged",
            heads=sorted(heads),
            detail=f"database has no Alembic version row; {_UPGRADE_HINT}",
        )
        return

    if current != heads:
        # Schema is behind code: any table added by a pending migration is missing,
        # so dependent sweeps fail every interval. Error, not warning.
        logger.error(
            "db.migrations_pending",
            db=sorted(current),
            heads=sorted(heads),
            pending=sorted(heads - current),
            detail=f"database schema is behind the latest migration; {_UPGRADE_HINT}",
        )
        return

    logger.debug("db.migrations_ok", heads=sorted(heads))
