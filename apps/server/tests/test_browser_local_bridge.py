"""Local Bridge session + execution gate (M1 · C1/C4)."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from agentcore.runtime.browser.desktop_bridge import (
    ensure_desktop_bridge_health,
    probe_desktop_bridge_sync,
    reset_desktop_bridge_health_for_tests,
    set_desktop_bridge_health_for_tests,
)
from agentcore.runtime.browser.local_session import LocalBridgeSession, open_local_bridge_session
from agentcore.runtime.browser.registry import BrowserSessionRegistry
from agentcore.tools.builtin.browser import BrowserNavigateTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.browser.protocol import BrowserSessionError, BrowserSessionRequest
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.delegate.conftest import LocalBackend


class _FakeBridgeHandler(BaseHTTPRequestHandler):
    """Minimal DesktopBrowserBridge stand-in for unit tests."""

    # Shared across requests in one server instance.
    navigations: list[dict] = []
    fail_host = False

    def log_message(self, *_args):  # noqa: D401 - silence test noise
        return

    def _auth_ok(self) -> bool:
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.server.token}"  # type: ignore[attr-defined]

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if self.path.startswith("/health"):
            self._json(200, {"ok": True, "service": "desktop-browser-bridge"})
            return
        self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth_ok():
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid_json"})
            return
        if self.__class__.fail_host:
            self._json(
                503,
                {"ok": False, "error": "host_unavailable: no window", "code": "host_unavailable"},
            )
            return
        if self.path.startswith("/command") or self.path.startswith("/navigate"):
            action = body.get("action") or "navigate"
            args = body.get("args") or body
            url = args.get("url") or body.get("url") or ""
            page_id = body.get("pageId") or body.get("session_id") or ""
            self.__class__.navigations.append(
                {"pageId": page_id, "action": action, "url": url, "args": args}
            )
            data: dict = {
                "final_url": url or "https://example.com/",
                "title": "Example Domain",
                "http_status": None,
            }
            if action == "screenshot":
                # Non-empty base64 + dims — LocalBridgeSession live poll contract.
                data["frame_b64"] = "Zm9v"  # b"foo"
                data["width"] = 1280
                data["height"] = 800
            self._json(200, {"ok": True, "data": data})
            return
        self._json(404, {"ok": False, "error": "not_found"})


@pytest.fixture()
def fake_bridge(monkeypatch):
    reset_desktop_bridge_health_for_tests()
    _FakeBridgeHandler.navigations = []
    _FakeBridgeHandler.fail_host = False
    server = HTTPServer(("127.0.0.1", 0), _FakeBridgeHandler)
    token = "test-bridge-token-abc"
    server.token = token  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("AGENTCORE_BROWSER_BRIDGE_URL", base)
    monkeypatch.setenv("AGENTCORE_BROWSER_BRIDGE_TOKEN", token)
    yield {"base": base, "token": token, "server": server}
    server.shutdown()
    reset_desktop_bridge_health_for_tests()


def test_probe_desktop_bridge_health(fake_bridge):
    assert probe_desktop_bridge_sync() is True
    assert ensure_desktop_bridge_health() is True


def test_turn_apply_clears_sticky_false(fake_bridge):
    """B-Arch-3: a failed probe must not pin the process after credentials refresh."""
    from agentcore.runtime.browser import desktop_bridge as db
    from agentcore.runtime.browser.desktop_bridge import apply_desktop_bridge_from_turn

    set_desktop_bridge_health_for_tests(False)
    assert ensure_desktop_bridge_health() is False

    apply_desktop_bridge_from_turn(
        {"baseUrl": fake_bridge["base"], "token": fake_bridge["token"]}
    )
    assert db.desktop_bridge_health() is None
    assert ensure_desktop_bridge_health() is True


def test_turn_apply_null_withholds(fake_bridge):
    from agentcore.runtime.browser.desktop_bridge import (
        apply_desktop_bridge_from_turn,
        desktop_bridge_configured,
    )

    apply_desktop_bridge_from_turn({"baseUrl": fake_bridge["base"], "token": fake_bridge["token"]})
    assert desktop_bridge_configured() is True
    apply_desktop_bridge_from_turn(None)
    assert desktop_bridge_configured() is False
    assert ensure_desktop_bridge_health() is False


@pytest.mark.asyncio
async def test_local_bridge_session_navigate_async(fake_bridge):
    from agentcore.tools.sandbox.browser.protocol import BrowserCommand

    sess = LocalBridgeSession(conversation_id="c1", session_id="sess-local-1")
    result = await sess.send(
        BrowserCommand(action="navigate", args={"url": "https://example.com/"})
    )
    assert result.ok
    assert result.data["final_url"] == "https://example.com/"
    assert _FakeBridgeHandler.navigations[-1]["pageId"] == "sess-local-1"
    assert _FakeBridgeHandler.navigations[-1]["action"] == "navigate"


@pytest.mark.asyncio
async def test_local_bridge_rewrites_relative_path_to_workspace(fake_bridge):
    """甲：LocalBridgeSession 相对路径 → workspace:// 再 POST Bridge。"""
    from agentcore.tools.sandbox.browser.protocol import BrowserCommand

    sess = LocalBridgeSession(conversation_id="Conv-ID", session_id="sess-ws")
    result = await sess.send(
        BrowserCommand(action="navigate", args={"url": "site/index.html"})
    )
    assert result.ok
    expected = "workspace://conv-id/site/index.html"
    assert result.data["final_url"] == expected
    assert _FakeBridgeHandler.navigations[-1]["url"] == expected
    assert _FakeBridgeHandler.navigations[-1]["args"]["url"] == expected


@pytest.mark.asyncio
async def test_local_bridge_rejects_file_url(fake_bridge):
    from agentcore.tools.sandbox.browser.protocol import BrowserCommand

    before = len(_FakeBridgeHandler.navigations)
    sess = LocalBridgeSession(conversation_id="c1", session_id="sess-bad")
    result = await sess.send(
        BrowserCommand(action="navigate", args={"url": "file:///tmp/x.html"})
    )
    assert not result.ok
    assert len(_FakeBridgeHandler.navigations) == before


@pytest.mark.asyncio
async def test_open_local_fails_without_bridge(monkeypatch):
    reset_desktop_bridge_health_for_tests()
    monkeypatch.delenv("AGENTCORE_BROWSER_BRIDGE_URL", raising=False)
    monkeypatch.delenv("AGENTCORE_BROWSER_BRIDGE_TOKEN", raising=False)
    set_desktop_bridge_health_for_tests(None)
    with pytest.raises(BrowserSessionError, match="host_unavailable"):
        await open_local_bridge_session(
            BrowserSessionRequest(conversation_id="c1", host_kind="local", session_id="s1")
        )


@pytest.mark.asyncio
async def test_tool_navigate_via_fake_bridge_updates_registry(fake_bridge, tmp_path: Path):
    set_desktop_bridge_health_for_tests(True)

    async def factory(req: BrowserSessionRequest):
        return await open_local_bridge_session(req)

    reg = BrowserSessionRegistry(factory=factory)
    backend = LocalBackend()
    # LocalBackend may not be a full WorkspaceBackend for write_bytes — use ServerWorkspace
    # for keyframe writes while keeping location=local via a thin wrapper.
    ws = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())

    class _LocalWs:
        location = "local"

        def __getattr__(self, name):
            return getattr(ws, name)

    ctx = ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="w1",
        backend=_LocalWs(),  # type: ignore[arg-type]
        user_id="u1",
        conversation_id="c-local",
    )
    tool = BrowserNavigateTool(registry=reg)
    result = await tool.execute({"url": "https://example.com/"}, ctx)
    assert result.success, result.output
    infos = reg.list_by_conversation("c-local")
    assert len(infos) == 1
    assert infos[0].host_kind == "local"
    assert infos[0].url == "https://example.com/"
    assert infos[0].title == "Example Domain"
    assert _FakeBridgeHandler.navigations
    assert _FakeBridgeHandler.navigations[0]["url"] == "https://example.com/"


@pytest.mark.asyncio
async def test_tool_host_unavailable_when_bridge_returns_503(fake_bridge, tmp_path: Path):
    _FakeBridgeHandler.fail_host = True
    set_desktop_bridge_health_for_tests(True)

    async def factory(req: BrowserSessionRequest):
        return await open_local_bridge_session(req)

    reg = BrowserSessionRegistry(factory=factory)
    ws = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())

    class _LocalWs:
        location = "local"

        def __getattr__(self, name):
            return getattr(ws, name)

    ctx = ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="w1",
        backend=_LocalWs(),  # type: ignore[arg-type]
        user_id="u1",
        conversation_id="c-local",
    )
    tool = BrowserNavigateTool(registry=reg)
    result = await tool.execute({"url": "https://example.com/"}, ctx)
    assert not result.success
    assert result.metadata and result.metadata.get("code") == "host_unavailable"


@pytest.mark.asyncio
async def test_local_screencast_start_emits_frames_and_stop_halts(fake_bridge):
    """Hub-style lifecycle: start_screencast polls Bridge screenshot → listener; stop cancels."""
    set_desktop_bridge_health_for_tests(True)
    sess = LocalBridgeSession(
        conversation_id="c1",
        session_id="sess-live-local",
        screencast_interval_s=0.05,
    )
    frames: list[dict] = []
    sess.set_frame_listener(lambda f: frames.append(dict(f)))

    await sess.start_screencast()
    # Wait for at least one poll cycle.
    for _ in range(40):
        if frames:
            break
        await asyncio.sleep(0.05)
    assert frames, "expected at least one live frame from Bridge screenshot poll"
    assert frames[0]["frame_b64"] == "Zm9v"
    assert frames[0]["width"] == 1280
    assert frames[0]["height"] == 800
    assert any(n["action"] == "screenshot" for n in _FakeBridgeHandler.navigations)

    before = len(frames)
    await sess.stop_screencast()
    assert sess._screencast_task is None or sess._screencast_task.done()
    shot_at_stop = sum(1 for n in _FakeBridgeHandler.navigations if n["action"] == "screenshot")
    await asyncio.sleep(0.2)
    assert len(frames) == before
    shot_after = sum(1 for n in _FakeBridgeHandler.navigations if n["action"] == "screenshot")
    assert shot_after == shot_at_stop  # no further Bridge captures after stop

    await sess.close()


@pytest.mark.asyncio
async def test_local_screencast_via_live_hub_attach_detach(fake_bridge):
    """Attach → local session starts poll; last detach (grace=0) → stop_screencast."""
    from agentcore.runtime.browser.live import BrowserLiveHub
    from agentcore.runtime.events.types import EventType

    set_desktop_bridge_health_for_tests(True)
    sess = LocalBridgeSession(
        conversation_id="c-hub",
        session_id="sess-hub-local",
        screencast_interval_s=0.05,
    )
    hub = BrowserLiveHub(
        session_lookup=lambda cid, sid=None: sess if cid == "c-hub" else None,
        grace_seconds=0.01,
        max_queued_frames=8,
    )
    viewer = await hub.attach("c-hub")
    started = await asyncio.wait_for(viewer.get(), timeout=1.0)
    assert started.type is EventType.BROWSER_LIVE_STATUS
    assert started.payload["state"] == "started"

    frame_ev = None
    for _ in range(40):
        try:
            ev = await asyncio.wait_for(viewer.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue
        if ev is not None and ev.type is EventType.BROWSER_LIVE_FRAME:
            frame_ev = ev
            break
    assert frame_ev is not None
    assert frame_ev.payload["frame_b64"] == "Zm9v"
    assert frame_ev.payload["width"] == 1280

    await hub.detach("c-hub", viewer)
    await asyncio.sleep(0.08)  # grace → stop
    assert sess._screencast_task is None or sess._screencast_task.done()
    await sess.close()

