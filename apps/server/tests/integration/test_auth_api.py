"""End-to-end API integration tests for auth + per-user isolation (real PG).

Exercises the full HTTP chain (cookies, DI, error mapping) against a real
PostgreSQL schema. Covers: unauthenticated 401s, the register/login/me flow,
owner-scoped conversation CRUD, IDOR protection, refresh rotation + reuse
detection, login lockout, and logout.
"""

from datetime import timedelta
from uuid import uuid4

from agentcore.config import settings
from tests.integration.conftest import login_admin, register_and_login

_PW = "password123"


async def test_protected_endpoints_require_auth(client):
    assert (await client.get("/v1/conversations")).status_code == 401
    assert (await client.post("/v1/conversations", json={"title": "x"})).status_code == 401
    assert (await client.get("/v1/auth/me")).status_code == 401


async def test_register_login_me_flow(client):
    r = await client.post(
        "/v1/auth/register",
        json={"username": "alice", "password": _PW},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "alice" and body["id"]

    r = await client.post("/v1/auth/login", json={"username": "alice", "password": _PW})
    assert r.status_code == 200
    assert "access_token" in client.cookies
    assert "refresh_token" in client.cookies

    r = await client.get("/v1/auth/me")
    assert r.status_code == 200 and r.json()["username"] == "alice"


async def test_register_closed_returns_403(client, monkeypatch):
    monkeypatch.setattr(settings, "registration_open", False)
    r = await client.post(
        "/v1/auth/register",
        json={"username": "bob", "password": _PW},
    )
    assert r.status_code == 403
    assert "注册已关闭" in r.text


async def test_conversation_crud_for_owner(client, make_invite):
    code = await make_invite("INV-2")
    await register_and_login(client, code, "carol")

    r = await client.post("/v1/conversations", json={"title": "hello"})
    assert r.status_code == 201
    conv_id = r.json()["id"]

    assert (await client.get("/v1/conversations")).json()["total"] == 1

    r = await client.get(f"/v1/conversations/{conv_id}")
    assert r.status_code == 200 and r.json()["id"] == conv_id

    r = await client.patch(f"/v1/conversations/{conv_id}", json={"title": "renamed"})
    assert r.status_code == 200 and r.json()["title"] == "renamed"

    assert (await client.delete(f"/v1/conversations/{conv_id}")).status_code == 200
    assert (await client.get("/v1/conversations")).json()["total"] == 0


async def test_idor_user_cannot_touch_others_conversation(client, new_client, make_invite):
    code1 = await make_invite("INV-A")
    await register_and_login(client, code1, "owner")
    conv_id = (await client.post("/v1/conversations", json={"title": "secret"})).json()["id"]

    code2 = await make_invite("INV-B")
    async with new_client() as attacker:
        await register_and_login(attacker, code2, "attacker")

        assert (await attacker.get(f"/v1/conversations/{conv_id}")).status_code == 404
        assert (
            await attacker.patch(f"/v1/conversations/{conv_id}", json={"title": "hacked"})
        ).status_code == 404
        assert (await attacker.delete(f"/v1/conversations/{conv_id}")).status_code == 404
        assert (
            await attacker.post(f"/v1/conversations/{conv_id}/messages", json={"content": "hi"})
        ).status_code == 404
        assert (await attacker.get("/v1/conversations")).json()["total"] == 0

    # owner's data is untouched
    r = await client.get(f"/v1/conversations/{conv_id}")
    assert r.status_code == 200 and r.json()["title"] == "secret"


async def test_refresh_rotates_cookie(client, make_invite):
    code = await make_invite("INV-3")
    await register_and_login(client, code, "dave")

    old_refresh = client.cookies.get("refresh_token")
    r = await client.post("/v1/auth/refresh")
    assert r.status_code == 200

    new_refresh = client.cookies.get("refresh_token")
    assert new_refresh and new_refresh != old_refresh
    # the freshly rotated access cookie still authorizes
    assert (await client.get("/v1/auth/me")).status_code == 200


async def test_refresh_reuse_detected_revokes_family(client, new_client, make_invite, monkeypatch):
    # Close the benign-concurrency grace window so an already-rotated token reads
    # as a genuine replay/leak (the security property under test). The within-grace
    # benign path is covered by tests/test_auth_service.py.
    monkeypatch.setattr("agentcore.auth.service._REFRESH_REUSE_GRACE", timedelta(0))
    code = await make_invite("INV-4")
    await register_and_login(client, code, "erin")

    r1 = client.cookies.get("refresh_token")
    assert (await client.post("/v1/auth/refresh")).status_code == 200
    r2 = client.cookies.get("refresh_token")
    assert r2 != r1

    # Replay the already-rotated r1 from a clean jar -> reuse detected (401).
    async with new_client() as raw:
        resp = await raw.post("/v1/auth/refresh", headers={"Cookie": f"refresh_token={r1}"})
        assert resp.status_code == 401

    # Reuse must revoke the whole family, so the live r2 is now dead too.
    async with new_client() as raw:
        resp = await raw.post("/v1/auth/refresh", headers={"Cookie": f"refresh_token={r2}"})
        assert resp.status_code == 401


async def test_login_lockout_after_repeated_failures(client, make_invite):
    code = await make_invite("INV-5")
    await register_and_login(client, code, "frank")

    for _ in range(5):
        r = await client.post(
            "/v1/auth/login", json={"username": "frank", "password": "wrong-pass"}
        )
        assert r.status_code == 401

    # Even the correct password is rejected while the account is locked.
    r = await client.post("/v1/auth/login", json={"username": "frank", "password": _PW})
    assert r.status_code == 401


async def test_logout_clears_cookies(client, make_invite):
    code = await make_invite("INV-6")
    await register_and_login(client, code, "gina")
    assert (await client.get("/v1/auth/me")).status_code == 200

    assert (await client.post("/v1/auth/logout")).status_code == 200
    # cookies cleared -> protected route is unauthenticated again
    assert (await client.get("/v1/auth/me")).status_code == 401


async def test_refresh_cookie_path_carries_reverse_proxy_prefix(client, make_invite, monkeypatch):
    # Behind the prod Nginx the API is mounted at /api/, so the browser's real refresh
    # path is /api/v1/auth/refresh. RFC 6265 path-matching only sends the cookie if its
    # Path is a prefix of that — a bare /v1/auth scope silently drops it (forced
    # re-login once the access token expires). COOKIE_PATH_PREFIX must carry the mount.
    monkeypatch.setattr(settings, "cookie_path_prefix", "/api")
    await make_invite("INV-PREFIX")
    r = await client.post(
        "/v1/auth/register",
        json={"username": "pat", "password": _PW},
    )
    assert r.status_code == 201, r.text
    r = await client.post("/v1/auth/login", json={"username": "pat", "password": _PW})
    assert r.status_code == 200

    set_cookies = r.headers.get_list("set-cookie")
    refresh = next(c for c in set_cookies if c.startswith("refresh_token="))
    assert "Path=/api/v1/auth" in refresh, refresh
    # Access cookie stays at root so it rides every /api/* request.
    access = next(c for c in set_cookies if c.startswith("access_token="))
    assert "Path=/" in access and "Path=/api/v1/auth" not in access, access


# --- self-service account ops (账户设置: 改密码 / 改资料 / 注销) ---


async def test_change_password_keeps_session_and_rotates_secret(client, make_invite):
    code = await make_invite("INV-CP-1")
    await register_and_login(client, code, "harry")

    r = await client.post(
        "/v1/auth/change-password",
        json={"current_password": _PW, "new_password": "newpassword456"},
    )
    assert r.status_code == 200, r.text
    # this session stays valid — the route re-issues fresh cookies
    assert (await client.get("/v1/auth/me")).status_code == 200
    # old password is dead; the new one logs in
    assert (
        await client.post("/v1/auth/login", json={"username": "harry", "password": _PW})
    ).status_code == 401
    assert (
        await client.post(
            "/v1/auth/login",
            json={"username": "harry", "password": "newpassword456"},
        )
    ).status_code == 200


async def test_change_password_wrong_current_rejected(client, make_invite):
    code = await make_invite("INV-CP-2")
    await register_and_login(client, code, "iris")
    r = await client.post(
        "/v1/auth/change-password",
        json={"current_password": "wrong-pw", "new_password": "newpassword456"},
    )
    assert r.status_code == 401


async def test_change_password_requires_auth(client):
    r = await client.post(
        "/v1/auth/change-password",
        json={"current_password": _PW, "new_password": "newpassword456"},
    )
    assert r.status_code == 401


async def test_update_profile_changes_display_name_and_email(client, make_invite):
    code = await make_invite("INV-UP-1")
    await register_and_login(client, code, "jack")

    r = await client.patch(
        "/v1/auth/me",
        json={"display_name": "Jack Jones", "email": "jack@example.com"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "Jack Jones"
    assert body["email"] == "jack@example.com"
    # persisted across a fresh read
    me = (await client.get("/v1/auth/me")).json()
    assert me["display_name"] == "Jack Jones" and me["email"] == "jack@example.com"


async def test_update_profile_rejects_duplicate_email(client, new_client, make_invite):
    code1 = await make_invite("INV-UP-2")
    await register_and_login(client, code1, "kate")
    assert (
        await client.patch("/v1/auth/me", json={"email": "shared@example.com"})
    ).status_code == 200

    code2 = await make_invite("INV-UP-3")
    async with new_client() as other:
        await register_and_login(other, code2, "liam")
        r = await other.patch("/v1/auth/me", json={"email": "shared@example.com"})
        assert r.status_code == 422


async def test_update_profile_requires_auth(client):
    assert (await client.patch("/v1/auth/me", json={"display_name": "x"})).status_code == 401


async def test_delete_account_anonymizes_and_frees_username(client, make_invite):
    code = await make_invite("INV-DEL-1")
    await register_and_login(client, code, "mona")
    # give the account data so the route's conversation cascade actually runs
    assert (await client.post("/v1/conversations", json={"title": "to be gone"})).status_code == 201

    r = await client.request("DELETE", "/v1/auth/me", json={"password": _PW})
    assert r.status_code == 200, r.text
    # cookies cleared → unauthenticated, and the old credentials are dead
    assert (await client.get("/v1/auth/me")).status_code == 401
    assert (
        await client.post("/v1/auth/login", json={"username": "mona", "password": _PW})
    ).status_code == 401
    # the username was anonymized away → a brand-new account can reclaim it
    await make_invite("INV-DEL-2")
    r = await client.post(
        "/v1/auth/register",
        json={"username": "mona", "password": _PW},
    )
    assert r.status_code == 201, r.text


async def test_delete_account_wrong_password_rejected(client, make_invite):
    code = await make_invite("INV-DEL-3")
    await register_and_login(client, code, "nate")
    r = await client.request("DELETE", "/v1/auth/me", json={"password": "wrong-pw"})
    assert r.status_code == 401
    # the account is untouched and still usable
    assert (await client.get("/v1/auth/me")).status_code == 200


async def test_delete_account_requires_auth(client):
    r = await client.request("DELETE", "/v1/auth/me", json={"password": _PW})
    assert r.status_code == 401


# --- bearer-token flow (mobile web / Capacitor shell, M2) ---


async def test_token_login_returns_tokens_and_authorizes_via_bearer(client, make_invite):
    await make_invite("INV-TOK-1")
    r = await client.post(
        "/v1/auth/register",
        json={"username": "mobile1", "password": _PW},
    )
    assert r.status_code == 201, r.text

    r = await client.post("/v1/auth/token", json={"username": "mobile1", "password": _PW})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert body["refresh_expires_in"] and body["refresh_expires_in"] > body["expires_in"]
    assert body["user"]["username"] == "mobile1"
    # The bearer flow sets NO cookies (it's for capacitor:// / new-origin clients).
    assert "access_token" not in client.cookies

    # The access token alone (no cookie) authorizes a protected route.
    me = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200 and me.json()["username"] == "mobile1"


async def test_bearer_invalid_token_rejected(client):
    r = await client.get("/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


async def test_token_refresh_rotates_via_body_and_detects_reuse(client, make_invite, monkeypatch):
    # Close the grace window so the old token re-presented after rotation reads as
    # a genuine reuse (benign within-grace concurrency is unit-tested separately).
    monkeypatch.setattr("agentcore.auth.service._REFRESH_REUSE_GRACE", timedelta(0))
    await make_invite("INV-TOK-2")
    await client.post(
        "/v1/auth/register",
        json={"username": "mobile2", "password": _PW},
    )
    tok = (
        await client.post("/v1/auth/token", json={"username": "mobile2", "password": _PW})
    ).json()

    r = await client.post("/v1/auth/token/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 200, r.text
    rotated = r.json()
    assert rotated["refresh_token"] != tok["refresh_token"]
    # the rotated access token authorizes
    me = await client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {rotated['access_token']}"},
    )
    assert me.status_code == 200

    # replaying the old (already-rotated) refresh token is reuse -> 401
    assert (
        await client.post("/v1/auth/token/refresh", json={"refresh_token": tok["refresh_token"]})
    ).status_code == 401


async def test_token_revoke_kills_refresh(client, make_invite):
    await make_invite("INV-TOK-3")
    await client.post(
        "/v1/auth/register",
        json={"username": "mobile3", "password": _PW},
    )
    tok = (
        await client.post("/v1/auth/token", json={"username": "mobile3", "password": _PW})
    ).json()

    assert (
        await client.post("/v1/auth/token/revoke", json={"refresh_token": tok["refresh_token"]})
    ).status_code == 200
    # a revoked refresh token can no longer rotate
    assert (
        await client.post("/v1/auth/token/refresh", json={"refresh_token": tok["refresh_token"]})
    ).status_code == 401


# --- invite issuance (admin) ---


async def test_invite_endpoints_require_auth(client):
    assert (await client.post("/v1/auth/invites", json={})).status_code == 401
    assert (await client.post("/v1/auth/invites/batch", json={"count": 2})).status_code == 401
    assert (await client.get("/v1/auth/invites")).status_code == 401
    assert (await client.get("/v1/auth/invites/stats")).status_code == 401


async def test_admin_issues_invite(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)

    r = await client.post("/v1/auth/invites", json={})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active" and body["code"]

    assert (await client.get("/v1/auth/invites")).json()["total"] == 1

    # Open registration succeeds without consuming the invite.
    r = await client.post(
        "/v1/auth/register",
        json={"username": "rookie", "password": _PW},
    )
    assert r.status_code == 201, r.text
    assert (await client.get("/v1/auth/invites")).json()["data"][0]["status"] == "active"


async def test_admin_batch_issues_invites(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)

    r = await client.post("/v1/auth/invites/batch", json={"count": 3})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["data"]) == 3
    codes = {item["code"] for item in body["data"]}
    assert len(codes) == 3
    assert all(item["status"] == "active" for item in body["data"])

    assert (await client.get("/v1/auth/invites")).json()["total"] == 3


async def test_batch_invite_rejects_invalid_count(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)
    assert (await client.post("/v1/auth/invites/batch", json={"count": 0})).status_code == 422
    assert (await client.post("/v1/auth/invites/batch", json={"count": 101})).status_code == 422


async def test_list_invites_paginated_and_filtered(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)

    await client.post("/v1/auth/invites/batch", json={"count": 5})

    page1 = (await client.get("/v1/auth/invites", params={"page": 1, "page_size": 2})).json()
    assert page1["total"] == 5
    assert page1["page"] == 1
    assert page1["page_size"] == 2
    assert len(page1["data"]) == 2

    page3 = (await client.get("/v1/auth/invites", params={"page": 3, "page_size": 2})).json()
    assert len(page3["data"]) == 1

    active = (await client.get("/v1/auth/invites", params={"status": "active"})).json()
    assert active["total"] == 5
    assert all(row["status"] == "active" for row in active["data"])


async def test_list_invites_search_by_code(client, make_admin, make_invite):
    await make_invite("ALPHA-SEARCH-01")
    await make_invite("ALPHA-SEARCH-02")
    await make_invite("BETA-OTHER-03")
    username, password = await make_admin()
    await login_admin(client, username, password)

    matched = (await client.get("/v1/auth/invites", params={"search": "ALPHA"})).json()
    assert matched["total"] == 2
    assert all("ALPHA" in row["code"] for row in matched["data"])

    single = (await client.get("/v1/auth/invites", params={"search": "BETA"})).json()
    assert single["total"] == 1
    assert single["data"][0]["code"] == "BETA-OTHER-03"


async def test_invite_stats_counts_by_status(client, make_admin, make_invite):
    await make_invite("STATS-A")
    await make_invite("STATS-B")
    username, password = await make_admin()
    await login_admin(client, username, password)

    stats = (await client.get("/v1/auth/invites/stats")).json()
    assert stats == {
        "total": 2,
        "active": 2,
        "used": 0,
        "expired": 0,
        "revoked": 0,
    }
    assert (await client.get("/v1/auth/invites")).json()["total"] == stats["total"]


async def test_non_admin_cannot_access_invites(client, make_invite):
    code = await make_invite("INV-USER")
    await register_and_login(client, code, "regular")
    assert (await client.post("/v1/auth/invites", json={})).status_code == 403
    assert (await client.post("/v1/auth/invites/batch", json={"count": 2})).status_code == 403
    assert (await client.get("/v1/auth/invites")).status_code == 403
    assert (await client.get("/v1/auth/invites/stats")).status_code == 403


# --- invite revocation (邀请码撤销) ---


async def test_admin_revokes_invite(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)

    body = (await client.post("/v1/auth/invites", json={})).json()
    invite_id = body["id"]

    r = await client.post(f"/v1/auth/invites/{invite_id}/revoke")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "revoked"

    listed = (await client.get("/v1/auth/invites")).json()["data"]
    assert listed[0]["status"] == "revoked"

    # Registration is open and no longer gated by invite status.
    r = await client.post(
        "/v1/auth/register",
        json={"username": "toolate", "password": _PW},
    )
    assert r.status_code == 201, r.text


async def test_revoke_used_invite_rejected(client, make_admin, session_factory):
    from datetime import UTC, datetime

    from agentcore.db.models import Invite

    username, password = await make_admin()
    await login_admin(client, username, password)
    body = (await client.post("/v1/auth/invites", json={})).json()
    invite_id = body["id"]

    async with session_factory() as session:
        invite = await session.get(Invite, invite_id)
        assert invite is not None
        invite.used_by = str(uuid4())
        invite.used_at = datetime.now(UTC)
        await session.commit()

    assert (await client.post(f"/v1/auth/invites/{invite_id}/revoke")).status_code == 422


async def test_revoke_invite_twice_rejected(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)
    invite_id = (await client.post("/v1/auth/invites", json={})).json()["id"]
    assert (await client.post(f"/v1/auth/invites/{invite_id}/revoke")).status_code == 200
    assert (await client.post(f"/v1/auth/invites/{invite_id}/revoke")).status_code == 422


async def test_revoke_unknown_invite_404(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)
    assert (await client.post(f"/v1/auth/invites/{uuid4()}/revoke")).status_code == 404


async def test_non_admin_cannot_revoke_invite(client, make_invite):
    code = await make_invite("INV-REVOKE-USER")
    await register_and_login(client, code, "regular2")
    assert (await client.post(f"/v1/auth/invites/{uuid4()}/revoke")).status_code == 403


async def test_admin_cannot_login_on_desktop(client, make_admin):
    username, password = await make_admin()
    r = await client.post(
        "/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-Client-Platform": "desktop"},
    )
    assert r.status_code == 403
    body = r.json()
    assert body["error"]["code"] == "ADMIN_PRODUCT_FORBIDDEN"


async def test_admin_mfa_login_flow(client, make_admin):
    username, password = await make_admin()
    await login_admin(client, username, password)
    assert (await client.get("/v1/admin/overview")).status_code == 200


async def test_admin_password_only_when_mfa_disabled(client, make_admin, monkeypatch):
    from agentcore.config import settings

    monkeypatch.setattr(settings, "admin_mfa_required", False)
    username, password = await make_admin()
    r = await client.post(
        "/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-Client-Platform": "admin"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mfa_required"] is False
    assert body["mfa_setup_required"] is False
    assert (await client.get("/v1/admin/overview")).status_code == 200


async def test_mfa_status_reports_required_flag(client, make_admin, monkeypatch):
    from agentcore.config import settings

    username, password = await make_admin()
    await login_admin(client, username, password)
    monkeypatch.setattr(settings, "admin_mfa_required", False)
    r = await client.get("/v1/auth/mfa/status")
    assert r.status_code == 200
    assert r.json()["required"] is False


# --- sessions (device management) ---


async def test_list_sessions_aggregates_and_marks_current(client, new_client, make_invite):
    await make_invite("INV-SESS-1")
    await register_and_login(client, "INV-SESS-1", "sess_alice")

    async with new_client() as other:
        r = await other.post(
            "/v1/auth/login", json={"username": "sess_alice", "password": _PW}
        )
        assert r.status_code == 200

    listed = await client.get("/v1/auth/sessions")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] >= 2
    currents = [s for s in body["data"] if s["current"]]
    assert len(currents) == 1
    assert currents[0]["platform"] == "desktop"
    assert "user_agent" in currents[0] and "ip" in currents[0]
    assert currents[0]["created_at"] and currents[0]["last_used_at"]


async def test_sessions_cross_user_family_404(client, new_client, make_invite):
    await make_invite("INV-SESS-A")
    await register_and_login(client, "INV-SESS-A", "sess_owner")
    family_id = (await client.get("/v1/auth/sessions")).json()["data"][0]["id"]

    await make_invite("INV-SESS-B")
    async with new_client() as attacker:
        await register_and_login(attacker, "INV-SESS-B", "sess_attacker")
        assert (
            await attacker.delete(f"/v1/auth/sessions/{family_id}")
        ).status_code == 404


async def test_revoke_session_blocks_refresh(client, make_invite):
    await make_invite("INV-SESS-2")
    await register_and_login(client, "INV-SESS-2", "sess_bob")
    family_id = (await client.get("/v1/auth/sessions")).json()["data"][0]["id"]
    assert (await client.delete(f"/v1/auth/sessions/{family_id}")).status_code == 200
    assert (await client.post("/v1/auth/refresh")).status_code == 401


async def test_revoke_others_keeps_current(client, new_client, make_invite):
    await make_invite("INV-SESS-3")
    await register_and_login(client, "INV-SESS-3", "sess_carol")

    async with new_client() as other:
        r = await other.post(
            "/v1/auth/login", json={"username": "sess_carol", "password": _PW}
        )
        assert r.status_code == 200
        other_refresh = other.cookies.get("refresh_token")

        assert (await client.post("/v1/auth/sessions/revoke-others")).status_code == 200
        # current device still refreshes
        assert (await client.post("/v1/auth/refresh")).status_code == 200
        # other device's refresh is dead
        resp = await other.post(
            "/v1/auth/refresh", headers={"Cookie": f"refresh_token={other_refresh}"}
        )
        assert resp.status_code == 401


async def test_family_max_days_rejects_refresh(client, make_invite, session_factory, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import select, update

    from agentcore.db.models import RefreshToken

    monkeypatch.setattr(settings, "refresh_family_max_days", 1)
    await make_invite("INV-SESS-4")
    await register_and_login(client, "INV-SESS-4", "sess_dave")

    async with session_factory() as session:
        result = await session.execute(select(RefreshToken))
        rows = list(result.scalars().all())
        assert rows
        await session.execute(
            update(RefreshToken).values(
                family_started_at=datetime.now(UTC) - timedelta(days=2)
            )
        )
        await session.commit()

    assert (await client.post("/v1/auth/refresh")).status_code == 401


async def test_admin_family_max_hours_rejects_refresh(
    client, make_admin, session_factory, monkeypatch
):
    from datetime import UTC, datetime

    from sqlalchemy import update

    from agentcore.db.models import RefreshToken

    monkeypatch.setattr(settings, "admin_mfa_required", False)
    monkeypatch.setattr(settings, "admin_refresh_family_max_hours", 1)
    username, password = await make_admin()
    r = await client.post(
        "/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-Client-Platform": "admin"},
    )
    assert r.status_code == 200, r.text

    async with session_factory() as session:
        await session.execute(
            update(RefreshToken).values(
                family_started_at=datetime.now(UTC) - timedelta(hours=2)
            )
        )
        await session.commit()

    assert (await client.post("/v1/auth/refresh")).status_code == 401


async def test_refresh_token_gc_keeps_active_tips(session_factory, monkeypatch):
    from datetime import UTC, datetime

    import agentcore.auth.retention as retention_mod
    from agentcore.auth.retention import run_refresh_token_retention_sweep
    from agentcore.db.models import RefreshToken
    from agentcore.db.repositories import CredentialsRepository, UserRepository
    from agentcore.security import hash_password, hash_refresh_token

    monkeypatch.setattr(settings, "refresh_token_retention_days", 7)
    monkeypatch.setattr(retention_mod, "async_session_factory", session_factory)

    async with session_factory() as session:
        user = await UserRepository(session).create(
            username=f"gc_{uuid4().hex[:8]}", display_name="GC"
        )
        await CredentialsRepository(session).create(
            user_id=user.user_id, password_hash=hash_password(_PW)
        )
        family = str(uuid4())
        live = RefreshToken(
            id=str(uuid4()),
            user_id=user.user_id,
            token_hash=hash_refresh_token(f"live-{uuid4().hex}"),
            token_family=family,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            client_aud="product",
            family_started_at=datetime.now(UTC),
            last_used_at=datetime.now(UTC),
        )
        old_rotated = RefreshToken(
            id=str(uuid4()),
            user_id=user.user_id,
            token_hash=hash_refresh_token(f"old-{uuid4().hex}"),
            token_family=family,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            client_aud="product",
            rotated_at=datetime.now(UTC) - timedelta(days=10),
            family_started_at=datetime.now(UTC) - timedelta(days=10),
            last_used_at=datetime.now(UTC) - timedelta(days=10),
        )
        session.add_all([live, old_rotated])
        await session.commit()
        live_id, old_id = live.id, old_rotated.id

    deleted = await run_refresh_token_retention_sweep()
    assert deleted >= 1

    async with session_factory() as session:
        assert await session.get(RefreshToken, live_id) is not None
        assert await session.get(RefreshToken, old_id) is None

