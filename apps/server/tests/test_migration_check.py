"""Unit tests for startup migration check / debug auto-upgrade."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentcore.config import settings
from agentcore.db import migration_check as mc


def _engine_with_connects(*cms: MagicMock) -> MagicMock:
    """Fake async engine whose ``connect()`` yields the given context managers in order."""
    engine = MagicMock()
    if len(cms) == 1:
        engine.connect = MagicMock(return_value=cms[0])
    else:
        engine.connect = MagicMock(side_effect=list(cms))
    return engine


def _async_cm(conn: MagicMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.fixture
def _isolate_settings(monkeypatch):
    """Ensure each test starts from a known debug flag."""
    monkeypatch.setattr(settings, "debug", False)


async def test_prod_skips_auto_upgrade(_isolate_settings, monkeypatch):
    """debug=false must never call alembic upgrade — only the drift notice path."""
    monkeypatch.setattr(settings, "debug", False)
    upgrade = AsyncMock()
    monkeypatch.setattr(mc, "_auto_upgrade_dev", upgrade)
    monkeypatch.setattr(mc, "_script_heads", lambda: {"aaa"})

    conn = MagicMock()
    conn.run_sync = AsyncMock(return_value={"aaa"})
    monkeypatch.setattr(mc, "engine", _engine_with_connects(_async_cm(conn)))

    await mc.check_migrations()
    upgrade.assert_not_awaited()


async def test_debug_attempts_auto_upgrade(_isolate_settings, monkeypatch):
    """debug=true runs auto-upgrade before the drift check."""
    monkeypatch.setattr(settings, "debug", True)
    upgrade = AsyncMock()
    monkeypatch.setattr(mc, "_auto_upgrade_dev", upgrade)
    monkeypatch.setattr(mc, "_script_heads", lambda: {"bbb"})

    conn = MagicMock()
    conn.run_sync = AsyncMock(return_value={"bbb"})
    monkeypatch.setattr(mc, "engine", _engine_with_connects(_async_cm(conn)))

    await mc.check_migrations()
    upgrade.assert_awaited_once()


async def test_upgrade_failure_does_not_raise(_isolate_settings, monkeypatch):
    """Alembic upgrade failure must not block startup; drift check still runs."""
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(mc, "_script_heads", lambda: {"head1"})

    preflight = MagicMock()
    preflight.run_sync = AsyncMock(return_value={"behind"})
    drift = MagicMock()
    drift.run_sync = AsyncMock(return_value={"behind"})
    monkeypatch.setattr(
        mc,
        "engine",
        _engine_with_connects(_async_cm(preflight), _async_cm(drift)),
    )
    monkeypatch.setattr(
        mc,
        "_upgrade_to_head",
        MagicMock(side_effect=RuntimeError("multiple heads")),
    )

    await mc.check_migrations()  # must not raise


async def test_auto_upgrade_noop_when_already_at_head(_isolate_settings, monkeypatch):
    """At-head short-circuit: no alembic command, quiet debug log only."""
    monkeypatch.setattr(mc, "_script_heads", lambda: {"head"})

    conn = MagicMock()
    conn.run_sync = AsyncMock(return_value={"head"})
    monkeypatch.setattr(mc, "engine", _engine_with_connects(_async_cm(conn)))

    upgrade_cmd = MagicMock()
    monkeypatch.setattr(mc, "_upgrade_to_head", upgrade_cmd)

    with patch.object(mc.logger, "debug") as debug_log:
        await mc._auto_upgrade_dev()

    upgrade_cmd.assert_not_called()
    debug_log.assert_any_call("db.migrations_upgrade_noop", heads=["head"])


async def test_auto_upgrade_logs_info_on_actual_upgrade(_isolate_settings, monkeypatch):
    """Successful revision change emits db.migrations_upgraded with before/after."""
    monkeypatch.setattr(mc, "_script_heads", lambda: {"new"})

    before = MagicMock()
    before.run_sync = AsyncMock(return_value={"old"})
    after = MagicMock()
    after.run_sync = AsyncMock(return_value={"new"})
    monkeypatch.setattr(
        mc,
        "engine",
        _engine_with_connects(_async_cm(before), _async_cm(after)),
    )
    monkeypatch.setattr(mc, "_upgrade_to_head", MagicMock())

    with patch.object(mc.logger, "info") as info_log:
        await mc._auto_upgrade_dev()

    info_log.assert_called_once_with(
        "db.migrations_upgraded",
        from_revisions=["old"],
        to_revisions=["new"],
    )


async def test_check_migrations_never_raises_on_db_error(_isolate_settings, monkeypatch):
    """Drift-check connection failures are swallowed (startup must continue)."""
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(mc, "_script_heads", MagicMock(side_effect=OSError("no db")))

    await mc.check_migrations()  # must not raise
