"""Integration tests for product notices (``/v1/notices*`` + ``/v1/admin/notices*``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.integration.conftest import login_admin, register_and_login

_PW = "password123"


async def _admin_login(client, make_admin, username: str = "notice-admin"):
    user, password = await make_admin(username, _PW)
    await login_admin(client, user, password)


async def _create_and_publish(
    client,
    *,
    title: str = "维护公告",
    body: str = "今晚维护",
    severity: str = "normal",
    surface: str = "both",
    dismiss_policy: str = "once",
    start_at: str | None = None,
    end_at: str | None = None,
) -> str:
    payload: dict = {
        "title": title,
        "body": body,
        "severity": severity,
        "surface": surface,
        "dismiss_policy": dismiss_policy,
    }
    if start_at is not None:
        payload["start_at"] = start_at
    if end_at is not None:
        payload["end_at"] = end_at
    r = await client.post("/v1/admin/notices", json=payload)
    assert r.status_code == 201, r.text
    notice_id = r.json()["id"]
    r = await client.post(f"/v1/admin/notices/{notice_id}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
    assert r.json()["published_at"] is not None
    return notice_id


async def test_publish_then_active_visible(client, make_admin, make_invite):
    await _admin_login(client, make_admin, "notice-pub-admin")
    notice_id = await _create_and_publish(
        client, title="上线公告", body="v1 已发布", severity="high", surface="both"
    )

    # switch to product user
    invite = await make_invite("NOTICE-PUB")
    await register_and_login(client, invite, "notice-pub-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["banner"] is not None
    assert body["banner"]["id"] == notice_id
    assert body["banner"]["title"] == "上线公告"
    assert body["banner"]["dismissed"] is False
    assert any(n["id"] == notice_id for n in body["inbox"])


async def test_dismiss_once_hides_banner(client, make_admin, make_invite):
    await _admin_login(client, make_admin, "notice-dismiss-admin")
    notice_id = await _create_and_publish(
        client, dismiss_policy="once", surface="banner", title="可关闭横幅"
    )

    invite = await make_invite("NOTICE-DISMISS")
    await register_and_login(client, invite, "notice-dismiss-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.json()["banner"]["id"] == notice_id

    r = await client.post(f"/v1/notices/{notice_id}/dismiss")
    assert r.status_code == 204, r.text

    # idempotent
    r = await client.post(f"/v1/notices/{notice_id}/dismiss")
    assert r.status_code == 204, r.text

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    assert r.json()["banner"] is None


async def test_never_cannot_dismiss(client, make_admin, make_invite):
    await _admin_login(client, make_admin, "notice-never-admin")
    notice_id = await _create_and_publish(
        client, dismiss_policy="never", surface="banner", title="不可关闭"
    )

    invite = await make_invite("NOTICE-NEVER")
    await register_and_login(client, invite, "notice-never-user", password=_PW)

    r = await client.post(f"/v1/notices/{notice_id}/dismiss")
    assert r.status_code == 409, r.text

    r = await client.get("/v1/notices/active")
    assert r.json()["banner"]["id"] == notice_id


async def test_outside_time_window_hidden(client, make_admin, make_invite):
    await _admin_login(client, make_admin, "notice-window-admin")
    past_end = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    future_start = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    expired_id = await _create_and_publish(
        client, title="已过期", end_at=past_end, surface="both"
    )
    future_id = await _create_and_publish(
        client, title="未开始", start_at=future_start, surface="both"
    )

    invite = await make_invite("NOTICE-WINDOW")
    await register_and_login(client, invite, "notice-window-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {n["id"] for n in body["inbox"]}
    if body["banner"]:
        ids.add(body["banner"]["id"])
    assert expired_id not in ids
    assert future_id not in ids


async def test_non_admin_cannot_access_admin_notices(client, make_invite):
    invite = await make_invite("NOTICE-NOADMIN")
    await register_and_login(client, invite, "notice-plain-user", password=_PW)

    r = await client.get("/v1/admin/notices")
    assert r.status_code == 403

    r = await client.post(
        "/v1/admin/notices",
        json={"title": "x", "body": "y", "severity": "normal", "surface": "banner"},
    )
    assert r.status_code == 403
