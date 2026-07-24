"""Integration: CSRF synchronizer token on cookie login flow."""

import pytest

from agentcore.middleware.csrf import CSRF_HEADER

_PW = "password123"


@pytest.mark.csrf
async def test_login_issues_csrf_and_allows_mutating_request(client):
    await client.post(
        "/v1/auth/register",
        json={"username": "csrfint", "password": _PW},
    )
    login = await client.post(
        "/v1/auth/login",
        json={"username": "csrfint", "password": _PW},
    )
    assert login.status_code == 200
    csrf = login.headers.get(CSRF_HEADER)
    assert csrf

    r = await client.post(
        "/v1/conversations",
        json={"title": "csrf-ok"},
        headers={CSRF_HEADER: csrf},
    )
    assert r.status_code == 201


@pytest.mark.csrf
async def test_me_reissues_csrf_for_resumed_session(client):
    """Session resumed via the access cookie (app cold start hits /me, not login):
    /me must hand back a usable CSRF token so the first mutating request succeeds."""
    await client.post(
        "/v1/auth/register",
        json={"username": "csrfme", "password": _PW},
    )
    # Login establishes the access cookie in the client jar; we deliberately ignore
    # the CSRF header it returns to mimic a client that has none yet.
    await client.post("/v1/auth/login", json={"username": "csrfme", "password": _PW})

    me = await client.get("/v1/auth/me")
    assert me.status_code == 200
    csrf = me.headers.get(CSRF_HEADER)
    assert csrf and csrf.startswith("v1.")

    r = await client.post(
        "/v1/conversations",
        json={"title": "me-csrf-ok"},
        headers={CSRF_HEADER: csrf},
    )
    assert r.status_code == 201
