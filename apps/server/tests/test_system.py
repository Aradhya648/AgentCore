"""Unit tests for the system probes: liveness, readiness, version, update policy.

The database probe is monkeypatched so readiness covers both the ready (200) and
not-ready (503) branches deterministically, without needing a live PostgreSQL.
"""

import httpx
from httpx import ASGITransport

from agentcore.api.routes import system
from agentcore.main import app


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_livez_is_always_alive_and_skips_dependencies(monkeypatch):
    # Liveness must never probe the DB, so a broken DB can't trip a restart loop.
    async def _must_not_run() -> bool:
        raise AssertionError("liveness must not probe the database")

    monkeypatch.setattr(system, "database_ready", _must_not_run)
    async with _client() as c:
        r = await c.get("/livez")

    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


async def test_readyz_returns_200_when_database_reachable(monkeypatch):
    async def _ready() -> bool:
        return True

    monkeypatch.setattr(system, "database_ready", _ready)
    monkeypatch.setattr(system, "redis_ready", _ready)
    async with _client() as c:
        r = await c.get("/readyz")

    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": True}


async def test_readyz_returns_503_when_database_down(monkeypatch):
    async def _down() -> bool:
        return False

    async def _redis_ok() -> bool:
        return True

    monkeypatch.setattr(system, "database_ready", _down)
    monkeypatch.setattr(system, "redis_ready", _redis_ok)
    async with _client() as c:
        r = await c.get("/readyz")

    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "database": False}


async def test_readyz_includes_redis_when_redis_backend(monkeypatch):
    async def _ready() -> bool:
        return True

    monkeypatch.setattr(system.settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(system, "database_ready", _ready)
    monkeypatch.setattr(system, "redis_ready", _ready)
    async with _client() as c:
        r = await c.get("/readyz")

    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": True, "redis": True}


async def test_readyz_returns_503_when_redis_required_but_down(monkeypatch):
    async def _db_ok() -> bool:
        return True

    async def _redis_down() -> bool:
        return False

    monkeypatch.setattr(system.settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(system, "database_ready", _db_ok)
    monkeypatch.setattr(system, "redis_ready", _redis_down)
    async with _client() as c:
        r = await c.get("/readyz")

    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "database": True, "redis": False}


async def test_version_exposes_build_provenance(monkeypatch):
    monkeypatch.setattr(system.settings, "git_sha", "abc1234")
    monkeypatch.setattr(system.settings, "built_at", "2026-06-15T00:00:00Z")
    async with _client() as c:
        r = await c.get("/version")

    assert r.status_code == 200
    body = r.json()
    assert body["git_sha"] == "abc1234"
    assert body["built_at"] == "2026-06-15T00:00:00Z"
    assert isinstance(body["version"], str) and body["version"]


async def test_updates_policy_enabled_by_default(monkeypatch):
    # Kill switch open by default; empty min version → null (no hard gate / no banner).
    monkeypatch.setattr(system.settings, "desktop_updates_enabled", True)
    monkeypatch.setattr(system.settings, "desktop_min_version", "")
    async with _client() as c:
        r = await c.get("/updates/policy")

    assert r.status_code == 200
    assert r.json() == {"enabled": True, "min_desktop_version": None}


async def test_updates_policy_reflects_kill_switch(monkeypatch):
    # Flipping the flag false is the kill switch that pauses downloads for a bad
    # release; the client honors it (fail-open only on transport/non-200, not this).
    monkeypatch.setattr(system.settings, "desktop_updates_enabled", False)
    monkeypatch.setattr(system.settings, "desktop_min_version", "")
    async with _client() as c:
        r = await c.get("/updates/policy")

    assert r.status_code == 200
    assert r.json() == {"enabled": False, "min_desktop_version": None}


async def test_updates_policy_exposes_min_desktop_version(monkeypatch):
    monkeypatch.setattr(system.settings, "desktop_updates_enabled", True)
    monkeypatch.setattr(system.settings, "desktop_min_version", "0.6.5")
    async with _client() as c:
        r = await c.get("/updates/policy")

    assert r.status_code == 200
    assert r.json() == {"enabled": True, "min_desktop_version": "0.6.5"}


async def test_updates_policy_blank_min_version_is_null(monkeypatch):
    monkeypatch.setattr(system.settings, "desktop_updates_enabled", True)
    monkeypatch.setattr(system.settings, "desktop_min_version", "  ")
    async with _client() as c:
        r = await c.get("/updates/policy")

    assert r.status_code == 200
    assert r.json()["min_desktop_version"] is None
