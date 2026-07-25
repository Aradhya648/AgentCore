"""Simulation show publish gate: non-admin rejected, admin allowed."""

from __future__ import annotations

import pytest

from agentcore.config import settings
from agentcore.simulation.show.catalog import get_meta, register_produced, reset_catalog
from agentcore.simulation.show.manifest import EpisodeManifest, EpisodeNextTeaser, EpisodeTickSpan
from agentcore.simulation.show.models import ShowEpisodeMeta
from tests.integration.conftest import login_admin, register_and_login

pytest_plugins = ["tests.integration.conftest"]

_PUBLISH_PATH = "/v1/admin/simulation/show/episodes/{episode_id}/publish"
_LEGACY_PRODUCT_PATH = "/v1/simulation/show/episodes/{episode_id}/publish"
TEST_PASSWORD = "password123"
_EPISODE_ID = "pub-auth-ep1"


def _seed_draft_episode() -> None:
    reset_catalog()
    register_produced(
        meta=ShowEpisodeMeta(
            episode_id=_EPISODE_ID,
            season_id="心动小镇",
            episode_no=1,
            title="鉴权测试期",
            run_id="run-pub-auth",
            tick_start=0,
            tick_end=10,
            publish_status="draft",
        ),
        manifest=EpisodeManifest(
            season="心动小镇",
            episode_no=1,
            title="鉴权测试期",
            run_id="run-pub-auth",
            tick_range=EpisodeTickSpan(start=0, end=10),
            next_teaser=EpisodeNextTeaser(title="下期", hook="hook"),
        ),
    )


def _meta_status() -> str:
    meta = get_meta(_EPISODE_ID)
    assert meta is not None
    return meta.publish_status


@pytest.fixture
def _sim_on(monkeypatch):
    monkeypatch.setattr(settings, "simulation_enabled", True)


@pytest.mark.asyncio
async def test_publish_rejects_plain_user(client, make_invite, _sim_on):
    _seed_draft_episode()
    invite = await make_invite("SIM-PUB-USER")
    await register_and_login(client, invite, "sim-pub-user", password=TEST_PASSWORD)

    r = await client.patch(
        _PUBLISH_PATH.format(episode_id=_EPISODE_ID),
        json={"publish_status": "review"},
    )
    assert r.status_code == 403
    assert _meta_status() == "draft"


@pytest.mark.asyncio
async def test_publish_allows_admin(client, make_admin, _sim_on):
    _seed_draft_episode()
    username, password = await make_admin("sim-pub-admin")
    await login_admin(client, username, password)

    r = await client.patch(
        _PUBLISH_PATH.format(episode_id=_EPISODE_ID),
        json={"publish_status": "review"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["episode_id"] == _EPISODE_ID
    assert body["publish_status"] == "review"
    assert _meta_status() == "review"


@pytest.mark.asyncio
async def test_legacy_product_publish_path_gone(client, make_invite, _sim_on):
    """旧产品路径已下线，任意登录用户不可再改发布态。"""
    _seed_draft_episode()
    invite = await make_invite("SIM-PUB-LEGACY")
    await register_and_login(client, invite, "sim-pub-legacy", password=TEST_PASSWORD)

    r = await client.patch(
        _LEGACY_PRODUCT_PATH.format(episode_id=_EPISODE_ID),
        json={"publish_status": "published"},
    )
    assert r.status_code == 404
    assert _meta_status() == "draft"
