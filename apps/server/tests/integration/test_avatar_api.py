"""End-to-end API integration tests for avatars (头像) against a real PG schema.

Covers the full self-service loop — upload (raw bytes) → derived ``avatar_url`` →
public serve → delete → 404 — plus auth gating, non-image rejection, and the
upload size cap. Asset storage is overridden with an in-memory fake so the suite
never touches disk or S3; the route/DI/serialization chain is the real thing.
"""

import io

import pytest
from PIL import Image

from agentcore.api.dependencies import get_asset_storage
from agentcore.config import settings
from agentcore.main import app
from tests.integration.conftest import register_and_login


class _MemoryAssets:
    """In-memory AssetStorage stand-in (no disk / S3) for hermetic route tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def assets():
    store = _MemoryAssets()
    app.dependency_overrides[get_asset_storage] = lambda: store
    try:
        yield store
    finally:
        app.dependency_overrides.pop(get_asset_storage, None)


def _png(width: int = 80, height: int = 120) -> bytes:
    img = Image.new("RGB", (width, height), (200, 60, 10))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


async def test_avatar_upload_serve_and_delete_roundtrip(client, new_client, make_invite, assets):
    code = await make_invite("INV-AV-1")
    await register_and_login(client, code, "ava")

    # No avatar to start.
    assert (await client.get("/v1/auth/me")).json()["avatar_url"] is None

    r = await client.post(
        "/v1/users/me/avatar",
        content=_png(),
        headers={"Content-Type": "image/png"},
    )
    assert r.status_code == 200, r.text
    avatar_url = r.json()["avatar_url"]
    assert avatar_url and "/v1/users/" in avatar_url and "?v=" in avatar_url
    # Exactly one object landed in storage (the processed WebP).
    assert len(assets.objects) == 1

    # The URL is public — a fresh client with no cookies can fetch the image.
    async with new_client() as anon:
        img = await anon.get(avatar_url)
        assert img.status_code == 200
        assert img.headers["content-type"] == "image/webp"
        assert img.content

    # /auth/me reflects the avatar across a fresh read.
    assert (await client.get("/v1/auth/me")).json()["avatar_url"] == avatar_url

    # Delete clears it server-side and the object is gone.
    r = await client.delete("/v1/users/me/avatar")
    assert r.status_code == 200, r.text
    assert r.json()["avatar_url"] is None
    assert assets.objects == {}

    # Serving now 404s.
    async with new_client() as anon:
        assert (await anon.get(avatar_url)).status_code == 404


async def test_avatar_upload_rejects_non_image(client, make_invite, assets):
    code = await make_invite("INV-AV-2")
    await register_and_login(client, code, "bob")
    r = await client.post(
        "/v1/users/me/avatar",
        content=b"not an image at all",
        headers={"Content-Type": "image/png"},
    )
    assert r.status_code == 422
    assert assets.objects == {}


async def test_avatar_upload_rejects_empty_body(client, make_invite, assets):
    code = await make_invite("INV-AV-3")
    await register_and_login(client, code, "cleo")
    r = await client.post(
        "/v1/users/me/avatar",
        content=b"",
        headers={"Content-Type": "image/png"},
    )
    assert r.status_code == 422


async def test_avatar_upload_rejects_oversized(client, make_invite, assets, monkeypatch):
    code = await make_invite("INV-AV-4")
    await register_and_login(client, code, "dan")
    # Shrink the cap below the test image so the size guard trips (Content-Length).
    monkeypatch.setattr(settings, "avatar_upload_max_bytes", 10)
    r = await client.post(
        "/v1/users/me/avatar",
        content=_png(),
        headers={"Content-Type": "image/png"},
    )
    assert r.status_code == 422
    assert assets.objects == {}


async def test_avatar_upload_and_delete_require_auth(client, assets):
    assert (
        await client.post(
            "/v1/users/me/avatar",
            content=_png(),
            headers={"Content-Type": "image/png"},
        )
    ).status_code == 401
    assert (await client.delete("/v1/users/me/avatar")).status_code == 401


async def test_avatar_serve_404_when_user_has_none(client, new_client, make_invite, assets):
    code = await make_invite("INV-AV-5")
    await register_and_login(client, code, "evan")
    user_id = (await client.get("/v1/auth/me")).json()["id"]
    async with new_client() as anon:
        assert (await anon.get(f"/v1/users/{user_id}/avatar")).status_code == 404


async def test_avatar_delete_is_idempotent(client, make_invite, assets):
    code = await make_invite("INV-AV-6")
    await register_and_login(client, code, "finn")
    # Deleting with no avatar set still succeeds with the unchanged user.
    r = await client.delete("/v1/users/me/avatar")
    assert r.status_code == 200
    assert r.json()["avatar_url"] is None
