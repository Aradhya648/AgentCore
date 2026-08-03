"""Unit tests for the desktop minimum-version hard gate middleware."""

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from agentcore.config import settings
from agentcore.middleware.client_version import (
    DesktopMinVersionMiddleware,
    compare_semver,
    is_desktop_version_outdated,
)

# --- pure helpers ---


def test_compare_semver_orders_major_minor_patch():
    assert compare_semver("0.6.24", "0.6.25") < 0
    assert compare_semver("0.6.25", "0.6.25") == 0
    assert compare_semver("0.7.0", "0.6.25") > 0
    assert compare_semver("0.6.25-beta", "0.6.25") == 0


def test_is_outdated_respects_floor_and_fail_open_inputs():
    assert is_desktop_version_outdated("0.6.24", "0.6.25") is True
    assert is_desktop_version_outdated("0.6.25", "0.6.25") is False
    assert is_desktop_version_outdated("dev", "0.6.25") is False
    assert is_desktop_version_outdated("", "0.6.25") is False
    assert is_desktop_version_outdated("0.6.24", "") is False


def test_is_outdated_raises_on_unparseable():
    with pytest.raises(ValueError):
        is_desktop_version_outdated("not-a-version", "0.6.25")


# --- middleware ---


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(DesktopMinVersionMiddleware)

    @app.get("/v1/ping")
    async def _ping():
        return {"ok": True}

    @app.post("/v1/auth/login")
    async def _login():
        return {"ok": True}

    @app.get("/updates/policy")
    async def _policy():
        return {"enabled": True, "min_desktop_version": "0.6.25"}

    @app.get("/livez")
    async def _livez():
        return {"status": "alive"}

    @app.options("/v1/ping")
    async def _options_ping():
        return {"ok": True}

    return app


def _headers(*, platform: str | None = "desktop", version: str | None = "0.6.24") -> dict:
    h: dict[str, str] = {}
    if platform is not None:
        h["X-Client-Platform"] = platform
    if version is not None:
        h["X-Client-Version"] = version
    return h


@pytest.fixture
def min_version(monkeypatch):
    monkeypatch.setattr(settings, "desktop_min_version", "0.6.25")


async def test_below_min_returns_426(min_version):
    transport = ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/v1/ping", headers=_headers(version="0.6.24"))
    assert r.status_code == 426
    body = r.json()["error"]
    assert body["code"] == "CLIENT_TOO_OLD"
    assert "0.6.25" in body["message"]
    assert body["details"]["min_version"] == "0.6.25"


async def test_at_or_above_min_passes(min_version):
    transport = ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (
            await c.get("/v1/ping", headers=_headers(version="0.6.25"))
        ).status_code == 200
        assert (
            await c.get("/v1/ping", headers=_headers(version="0.6.26"))
        ).status_code == 200
        # Auth path is also gated, but current version must pass.
        assert (
            await c.post("/v1/auth/login", headers=_headers(version="0.6.25"))
        ).status_code == 200


async def test_non_desktop_passes(min_version):
    transport = ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        for platform in ("web", "mobile", "admin"):
            r = await c.get(
                "/v1/ping", headers=_headers(platform=platform, version="0.6.24")
            )
            assert r.status_code == 200, platform
        # Missing platform header → not gated.
        r = await c.get("/v1/ping", headers=_headers(platform=None, version="0.6.24"))
        assert r.status_code == 200


async def test_missing_or_dev_version_fail_open(min_version):
    transport = ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (
            await c.get("/v1/ping", headers=_headers(version=None))
        ).status_code == 200
        assert (
            await c.get("/v1/ping", headers=_headers(version="dev"))
        ).status_code == 200
        # Unparseable → fail-open.
        assert (
            await c.get("/v1/ping", headers=_headers(version="???"))
        ).status_code == 200


async def test_empty_desktop_min_version_disables_gate(monkeypatch):
    monkeypatch.setattr(settings, "desktop_min_version", "")
    transport = ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/v1/ping", headers=_headers(version="0.0.1"))
    assert r.status_code == 200


async def test_updates_policy_and_probes_exempt(min_version):
    transport = ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        h = _headers(version="0.6.24")
        assert (await c.get("/updates/policy", headers=h)).status_code == 200
        assert (await c.get("/livez", headers=h)).status_code == 200
        # OPTIONS always exempt.
        assert (await c.options("/v1/ping", headers=h)).status_code == 200
