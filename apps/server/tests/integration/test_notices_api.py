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
    cta_label: str | None = None,
    cta_url: str | None = None,
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
    if cta_label is not None:
        payload["cta_label"] = cta_label
    if cta_url is not None:
        payload["cta_url"] = cta_url
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


async def test_publish_then_active_visible(client, make_admin):
    await _admin_login(client, make_admin, "notice-pub-admin")
    notice_id = await _create_and_publish(
        client, title="上线公告", body="v1 已发布", severity="high", surface="both"
    )

    # switch to product user
    await register_and_login(client, "notice-pub-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["banner"] is not None
    assert body["banner"]["id"] == notice_id
    assert body["banner"]["title"] == "上线公告"
    assert body["banner"]["dismissed"] is False
    assert any(n["id"] == notice_id for n in body["inbox"])


async def test_dismiss_once_hides_banner(client, make_admin):
    await _admin_login(client, make_admin, "notice-dismiss-admin")
    notice_id = await _create_and_publish(
        client, dismiss_policy="once", surface="banner", title="可关闭横幅"
    )

    await register_and_login(client, "notice-dismiss-user", password=_PW)

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


async def test_never_cannot_dismiss(client, make_admin):
    await _admin_login(client, make_admin, "notice-never-admin")
    notice_id = await _create_and_publish(
        client, dismiss_policy="never", surface="banner", title="不可关闭"
    )

    await register_and_login(client, "notice-never-user", password=_PW)

    r = await client.post(f"/v1/notices/{notice_id}/dismiss")
    assert r.status_code == 409, r.text

    r = await client.get("/v1/notices/active")
    assert r.json()["banner"]["id"] == notice_id


async def test_outside_time_window_hidden(client, make_admin):
    await _admin_login(client, make_admin, "notice-window-admin")
    past_end = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    future_start = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    expired_id = await _create_and_publish(
        client, title="已过期", end_at=past_end, surface="both"
    )
    future_id = await _create_and_publish(
        client, title="未开始", start_at=future_start, surface="both"
    )

    await register_and_login(client, "notice-window-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {n["id"] for n in body["inbox"]}
    if body["banner"]:
        ids.add(body["banner"]["id"])
    assert expired_id not in ids
    assert future_id not in ids


async def test_non_admin_cannot_access_admin_notices(client):
    await register_and_login(client, "notice-plain-user", password=_PW)

    r = await client.get("/v1/admin/notices")
    assert r.status_code == 403

    r = await client.post(
        "/v1/admin/notices",
        json={"title": "x", "body": "y", "severity": "normal", "surface": "banner"},
    )
    assert r.status_code == 403


async def test_publish_inbox_writes_official_im_message(client, make_admin):
    """surface=inbox → one shared system_card in the official broadcast chat."""
    await _admin_login(client, make_admin, "notice-im-admin")
    notice_id = await _create_and_publish(
        client,
        title="IM 公告",
        body="写入官方号",
        severity="high",
        surface="inbox",
        cta_label="查看",
        cta_url="https://example.com/n",
    )

    await register_and_login(client, "notice-im-user", password=_PW)

    r = await client.get("/v1/messages/chats")
    assert r.status_code == 200, r.text
    official = next((c for c in r.json()["data"] if c["type"] == "official"), None)
    assert official is not None
    assert official["pinned"] is True

    r = await client.get(f"/v1/messages/chats/{official['id']}/messages")
    assert r.status_code == 200, r.text
    messages = r.json()["data"]
    hits = [
        m
        for m in messages
        if m.get("payload", {}).get("kind") == "product_notice"
        and m["payload"].get("notice_id") == notice_id
    ]
    assert len(hits) == 1
    msg = hits[0]
    assert msg["sender_type"] == "official"
    assert msg["content_type"] == "system_card"
    assert msg["content"] == "IM 公告\n写入官方号"
    assert msg["payload"]["severity"] == "high"
    assert msg["payload"]["cta_label"] == "查看"
    assert msg["payload"]["cta_url"] == "https://example.com/n"

    # Users cannot send into / leave the official chat.
    r = await client.post(
        f"/v1/messages/chats/{official['id']}/messages",
        json={"content": "hi", "content_type": "text"},
    )
    assert r.status_code == 422, r.text
    r = await client.post(f"/v1/messages/chats/{official['id']}/leave")
    assert r.status_code == 422, r.text


async def test_publish_banner_skips_official_im(client, make_admin):
    await _admin_login(client, make_admin, "notice-banner-im-admin")
    await _create_and_publish(client, title="仅横幅", body="no im", surface="banner")

    await register_and_login(client, "notice-banner-im-user", password=_PW)

    r = await client.get("/v1/messages/chats")
    assert r.status_code == 200, r.text
    official = next((c for c in r.json()["data"] if c["type"] == "official"), None)
    assert official is not None
    r = await client.get(f"/v1/messages/chats/{official['id']}/messages")
    assert r.status_code == 200, r.text
    assert not any(
        m.get("payload", {}).get("kind") == "product_notice" for m in r.json()["data"]
    )


async def test_modal_active_and_inbox(client, make_admin):
    """surface=modal → active.modal + inbox; dismiss clears modal."""
    await _admin_login(client, make_admin, "notice-modal-admin")
    notice_id = await _create_and_publish(
        client,
        title="政策弹窗",
        body="额度调整说明",
        severity="normal",
        surface="modal",
        dismiss_policy="once",
    )

    await register_and_login(client, "notice-modal-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modal"] is not None
    assert body["modal"]["id"] == notice_id
    assert body["modal"]["dismissed"] is False
    assert any(n["id"] == notice_id for n in body["inbox"])
    # No competing banner in this fixture.
    assert body["banner"] is None

    r = await client.post(f"/v1/notices/{notice_id}/dismiss")
    assert r.status_code == 204, r.text

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modal"] is None
    # inbox still lists the notice with dismissed=true
    hit = next(n for n in body["inbox"] if n["id"] == notice_id)
    assert hit["dismissed"] is True


async def test_modal_suppresses_non_critical_banner(client, make_admin):
    """Undismissed modal suppresses non-critical banner."""
    await _admin_login(client, make_admin, "notice-modal-suppress-admin")
    modal_id = await _create_and_publish(
        client, title="弹窗", body="m", surface="modal", severity="normal"
    )
    await _create_and_publish(
        client, title="高优横幅", body="b", surface="banner", severity="high"
    )

    await register_and_login(client, "notice-modal-suppress-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modal"]["id"] == modal_id
    assert body["banner"] is None


async def test_modal_banner_priority(client, make_admin):
    """critical banner coexists with modal; normal/high banner is suppressed."""
    await _admin_login(client, make_admin, "notice-prio-admin")
    modal_id = await _create_and_publish(
        client, title="弹窗", body="m", surface="modal", severity="normal"
    )
    await _create_and_publish(
        client, title="高优横幅", body="h", surface="banner", severity="high"
    )
    critical_id = await _create_and_publish(
        client, title="紧急横幅", body="c", surface="banner", severity="critical"
    )

    await register_and_login(client, "notice-prio-user", password=_PW)

    r = await client.get("/v1/notices/active")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["modal"]["id"] == modal_id
    # critical wins over modal suppression
    assert body["banner"] is not None
    assert body["banner"]["id"] == critical_id
    assert body["banner"]["severity"] == "critical"


async def test_publish_modal_writes_official_im(client, make_admin):
    await _admin_login(client, make_admin, "notice-modal-im-admin")
    notice_id = await _create_and_publish(
        client, title="弹窗 IM", body="同步官方号", surface="modal"
    )

    await register_and_login(client, "notice-modal-im-user", password=_PW)

    r = await client.get("/v1/messages/chats")
    assert r.status_code == 200, r.text
    official = next((c for c in r.json()["data"] if c["type"] == "official"), None)
    assert official is not None
    r = await client.get(f"/v1/messages/chats/{official['id']}/messages")
    assert r.status_code == 200, r.text
    hits = [
        m
        for m in r.json()["data"]
        if m.get("payload", {}).get("kind") == "product_notice"
        and m["payload"].get("notice_id") == notice_id
    ]
    assert len(hits) == 1


async def test_modal_never_rejected_on_create_and_update(client, make_admin):
    await _admin_login(client, make_admin, "notice-modal-never-admin")

    r = await client.post(
        "/v1/admin/notices",
        json={
            "title": "坏弹窗",
            "body": "x",
            "severity": "normal",
            "surface": "modal",
            "dismiss_policy": "never",
        },
    )
    assert r.status_code == 400, r.text

    # Create a valid modal, then patch dismiss_policy → never
    r = await client.post(
        "/v1/admin/notices",
        json={
            "title": "好弹窗",
            "body": "y",
            "severity": "normal",
            "surface": "modal",
            "dismiss_policy": "once",
        },
    )
    assert r.status_code == 201, r.text
    notice_id = r.json()["id"]

    r = await client.patch(
        f"/v1/admin/notices/{notice_id}",
        json={"dismiss_policy": "never"},
    )
    assert r.status_code == 400, r.text

    # Create banner+never, then patch surface → modal
    r = await client.post(
        "/v1/admin/notices",
        json={
            "title": "永不关横幅",
            "body": "z",
            "severity": "normal",
            "surface": "banner",
            "dismiss_policy": "never",
        },
    )
    assert r.status_code == 201, r.text
    banner_id = r.json()["id"]
    r = await client.patch(
        f"/v1/admin/notices/{banner_id}",
        json={"surface": "modal"},
    )
    assert r.status_code == 400, r.text
