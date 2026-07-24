"""CSRF middleware tests (stateless HMAC-signed token, cookie-session clients)."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from agentcore.api.dependencies import ACCESS_TOKEN_COOKIE
from agentcore.config import settings
from agentcore.core.types import new_id
from agentcore.main import app
from agentcore.middleware.csrf import CSRF_HEADER, issue_csrf_token
from agentcore.security import create_access_token, sign_csrf_token, verify_csrf_token


@pytest.fixture
def csrf_enabled(monkeypatch):
    monkeypatch.setattr(settings, "csrf_enabled", True)


@pytest.mark.asyncio
async def test_csrf_blocks_mutating_request_without_header(csrf_enabled):
    user_id = new_id()
    token = create_access_token(user_id, audience="product")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(ACCESS_TOKEN_COOKIE, token)
        r = await client.post("/v1/conversations", json={"title": "nope"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.asyncio
async def test_csrf_allows_mutating_request_with_valid_header(csrf_enabled):
    user_id = new_id()
    token = create_access_token(user_id, audience="product")
    csrf = sign_csrf_token(user_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(ACCESS_TOKEN_COOKIE, token)
        # Auth will 401 (no DB user) — CSRF must pass first; we only assert not 403.
        r = await client.post(
            "/v1/conversations",
            json={"title": "ok"},
            headers={CSRF_HEADER: csrf},
        )
        assert r.status_code != 403


@pytest.mark.asyncio
async def test_csrf_rejects_token_minted_for_another_user(csrf_enabled):
    """A signed token is bound to its user_id; presenting it under a different
    session's access cookie must fail (stateless binding, not just any valid sig)."""
    user_id = new_id()
    other_id = new_id()
    token = create_access_token(user_id, audience="product")
    foreign_csrf = sign_csrf_token(other_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(ACCESS_TOKEN_COOKIE, token)
        r = await client.post(
            "/v1/conversations",
            json={"title": "nope"},
            headers={CSRF_HEADER: foreign_csrf},
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.asyncio
async def test_csrf_enforced_when_cookie_present_despite_bearer_header(csrf_enabled):
    """SEC-003: a session-cookie request must still pass CSRF even if it also carries
    an Authorization header. The auth layer prefers the cookie, so a bogus bearer must
    not let a cross-site request skip CSRF (which would collapse protection onto CORS)."""
    user_id = new_id()
    token = create_access_token(user_id, audience="product")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(ACCESS_TOKEN_COOKIE, token)
        r = await client.post(
            "/v1/conversations",
            json={"title": "nope"},
            headers={"Authorization": "Bearer anything"},
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "CSRF_FAILED"


@pytest.mark.asyncio
async def test_csrf_exempt_for_pure_bearer_client_without_cookie(csrf_enabled):
    """A genuine bearer client (mobile) sends no session cookie, so CSRF does not
    apply — it is not 403'd for a missing CSRF header (downstream auth handles it)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/v1/conversations",
            json={"title": "ok"},
            headers={"Authorization": "Bearer anything"},
        )
        assert r.status_code != 403


def test_issue_csrf_token_sets_header_and_is_verifiable():
    resp = Response()
    token = issue_csrf_token(resp, "u1")
    assert resp.headers[CSRF_HEADER] == token
    assert verify_csrf_token("u1", token)
    # Stateless + bound: the same token does not verify for a different user.
    assert not verify_csrf_token("u2", token)
