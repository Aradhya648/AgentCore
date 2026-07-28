"""Browser tools: D11 governance five-dim, cloud/local gate, execute + keyframe caps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.core.types import AutonomyPolicy, ToolApproval, ToolCategory, recipe_to_axes
from agentcore.runtime.browser.desktop_bridge import (
    reset_desktop_bridge_health_for_tests,
    set_desktop_bridge_health_for_tests,
)
from agentcore.runtime.browser.keyframes import KeyframeTracker
from agentcore.tools.builtin import browser_execution_enabled_for, build_worker_registry
from agentcore.tools.builtin.browser import (
    BROWSER_TOOL_CLASSES,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registration import AUDIENCE_WORKER_ONLY, ToolSurface, tool_registration
from agentcore.tools.sandbox.browser.protocol import (
    BrowserCommandResult,
    BrowserDriverCrashedError,
    BrowserSessionAcquireError,
    BrowserSessionsBusyError,
)
from agentcore.tools.sandbox.cloud_health import set_cloud_sandbox_health_for_tests
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace
from tests.delegate.conftest import LocalBackend

_BROWSER_NAMES = frozenset(
    {
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_scroll",
        "browser_snapshot",
        "browser_screenshot",
    }
)


# -- governance (D11 五维) ------------------------------------------------------
def test_all_six_tools_share_the_governance_five_dim():
    seen = set()
    for cls in BROWSER_TOOL_CLASSES:
        reg = tool_registration(cls)
        schema = cls().schema
        seen.add(schema.name)
        assert reg.surface is ToolSurface.WORKER_ONLY
        assert reg.audience == AUDIENCE_WORKER_ONLY
        assert reg.execution_class is True
        assert reg.browser_class is True
        assert schema.approval is ToolApproval.GRANTABLE
        assert schema.category is ToolCategory.EXECUTION
    assert seen == _BROWSER_NAMES


# -- cloud / local gate --------------------------------------------------------
def _server_backend(tmp_path: Path) -> ServerWorkspace:
    return ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())


def test_gate_requires_server_plus_gvisor_plus_health(tmp_path, monkeypatch):
    backend = _server_backend(tmp_path)
    assert browser_execution_enabled_for(None) is False
    reset_desktop_bridge_health_for_tests()
    assert browser_execution_enabled_for(LocalBackend()) is False  # local: no Bridge
    monkeypatch.setattr(settings, "gvisor_enabled", False)
    assert browser_execution_enabled_for(backend) is False  # no gVisor isolation
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    assert browser_execution_enabled_for(backend) is True
    set_cloud_sandbox_health_for_tests(False)
    assert browser_execution_enabled_for(backend) is False  # probe says unhealthy


def test_gate_local_requires_desktop_bridge_health(monkeypatch):
    reset_desktop_bridge_health_for_tests()
    assert browser_execution_enabled_for(LocalBackend()) is False
    set_desktop_bridge_health_for_tests(True)
    assert browser_execution_enabled_for(LocalBackend()) is True
    set_desktop_bridge_health_for_tests(False)
    assert browser_execution_enabled_for(LocalBackend()) is False
    reset_desktop_bridge_health_for_tests()


def test_worker_registry_includes_browser_only_on_gvisor_cloud(tmp_path, monkeypatch):
    backend = _server_backend(tmp_path)
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    names = {s.name for s in build_worker_registry(backend=backend).list_all()}
    assert names >= _BROWSER_NAMES

    # CAUTIOUS (command=ask) withholds the whole execution class (browser included).
    observe = {
        s.name
        for s in build_worker_registry(
            backend=backend, permission_axes=recipe_to_axes(AutonomyPolicy.CAUTIOUS)
        ).list_all()
    }
    assert not (_BROWSER_NAMES & observe)


def test_worker_registry_excludes_browser_without_gvisor(tmp_path, monkeypatch):
    backend = _server_backend(tmp_path)
    monkeypatch.setattr(settings, "gvisor_enabled", False)
    names = {s.name for s in build_worker_registry(backend=backend).list_all()}
    assert not (_BROWSER_NAMES & names)


def test_worker_registry_excludes_browser_on_local_without_bridge(monkeypatch):
    reset_desktop_bridge_health_for_tests()
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    names = {s.name for s in build_worker_registry(backend=LocalBackend()).list_all()}
    assert not (_BROWSER_NAMES & names)


def test_worker_registry_includes_browser_on_local_with_bridge(monkeypatch):
    set_desktop_bridge_health_for_tests(True)
    names = {s.name for s in build_worker_registry(backend=LocalBackend()).list_all()}
    assert names >= _BROWSER_NAMES
    reset_desktop_bridge_health_for_tests()


# -- execute -------------------------------------------------------------------
class _FakeSession:
    def __init__(self, result=None, crash=False):
        self._result = result
        self._crash = crash
        self.sent = []

    async def send(self, command):
        self.sent.append(command)
        if self._crash:
            raise BrowserDriverCrashedError("driver died")
        return self._result


class _FakeRegistry:
    def __init__(
        self,
        session=None,
        keyframes=None,
        busy=False,
        taken_over=False,
        acquire_error: BrowserSessionAcquireError | None = None,
    ):
        self._session = session
        self._keyframes = keyframes or KeyframeTracker()
        self._busy = busy
        self._taken_over = taken_over
        self._acquire_error = acquire_error
        self.closed: list[str] = []

    def is_taken_over(self, cid, *, session_id=None, run_id=None):
        # M2 接管互斥: the tool consults this before acquiring; default False (no takeover).
        return self._taken_over

    def peek_entry(self, cid, *, session_id=None, run_id=None):
        if self._session is None:
            return None
        from types import SimpleNamespace

        # Fake single-tab: session_id mirrors conversation for crash-drop assertions.
        return SimpleNamespace(session_id=cid)

    async def acquire(self, request):
        if self._busy:
            raise BrowserSessionsBusyError("云端浏览器会话已满")
        if self._acquire_error is not None:
            raise self._acquire_error
        return self._session, self._keyframes

    async def close(self, cid):
        self.closed.append(cid)

    async def close_session(self, session_id):
        self.closed.append(session_id)


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        execution_id="e1",
        run_id="r1",
        agent_id="w1",
        backend=ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox()),
        user_id="u1",
        conversation_id="c1",
    )


@pytest.mark.asyncio
async def test_navigate_builds_display_contract_and_writes_keyframe(tmp_path):
    session = _FakeSession(
        BrowserCommandResult(
            ok=True,
            data={"final_url": "https://example.com/", "title": "Example Domain", "http_status": 200},
            frame=b"\xff\xd8\xff\xe0jpeg",
        )
    )
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({"url": "https://example.com/"}, _ctx(tmp_path))

    assert result.success
    d = result.display
    assert d["kind"] == "browser" and d["action"] == "navigate"
    assert d["url"] == "https://example.com/" and d["title"] == "Example Domain"
    assert d["frame"] == "browser/step-0001.jpg"
    # A 推送绑页：成功路径必带 session_id + host_kind（FakeRegistry peek → cid）。
    assert d["session_id"] == "c1" and d["host_kind"] == "sandbox"
    # keyframe actually landed in the workspace (引用即驻留)
    assert (tmp_path / "browser" / "step-0001.jpg").read_bytes() == b"\xff\xd8\xff\xe0jpeg"
    # model-facing output is JSON with an untrusted-content boundary
    payload = json.loads(result.output)
    assert payload["action"] == "navigate" and payload["http_status"] == 200
    assert payload["untrusted_web_content"]["source_url"] == "https://example.com/"
    assert "note" in payload["untrusted_web_content"]


@pytest.mark.asyncio
async def test_snapshot_wraps_tree_untrusted_no_keyframe(tmp_path):
    session = _FakeSession(
        BrowserCommandResult(
            ok=True,
            data={
                "final_url": "https://example.com/",
                "title": "Example Domain",
                "snapshot_version": 1,
                "elements": "[e1] link: More",
                "aria": "- document",
            },
        )
    )
    tool = BrowserSnapshotTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({}, _ctx(tmp_path))
    assert result.success
    assert "frame" not in result.display  # read-only action captures no keyframe
    payload = json.loads(result.output)
    uw = payload["untrusted_web_content"]
    assert uw["elements"] == "[e1] link: More" and uw["accessibility_tree"] == "- document"
    assert payload["snapshot_version"] == 1


@pytest.mark.asyncio
async def test_busy_returns_explainable_failure(tmp_path):
    tool = BrowserNavigateTool(registry=_FakeRegistry(busy=True))
    result = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert not result.success and "已满" in result.output


@pytest.mark.asyncio
async def test_acquire_session_not_found_metadata_code(tmp_path):
    tool = BrowserNavigateTool(
        registry=_FakeRegistry(
            acquire_error=BrowserSessionAcquireError(
                "session_not_found: 浏览器会话不存在（x）",
                code="session_not_found",
            )
        )
    )
    result = await tool.execute({"url": "https://x/", "session_id": "x"}, _ctx(tmp_path))
    assert not result.success
    assert (result.metadata or {}).get("code") == "session_not_found"


@pytest.mark.asyncio
async def test_acquire_session_bound_elsewhere_metadata_code(tmp_path):
    tool = BrowserNavigateTool(
        registry=_FakeRegistry(
            acquire_error=BrowserSessionAcquireError(
                "session_bound_elsewhere: 浏览器会话已绑定 local",
                code="session_bound_elsewhere",
            )
        )
    )
    result = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert not result.success
    assert (result.metadata or {}).get("code") == "session_bound_elsewhere"


@pytest.mark.asyncio
async def test_driver_crash_drops_session_and_informs(tmp_path):
    reg = _FakeRegistry(session=_FakeSession(crash=True))
    tool = BrowserNavigateTool(registry=reg)
    result = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert not result.success
    assert "页面状态已丢失" in result.output and "重新开始" in result.output
    assert reg.closed == ["c1"]  # dead session dropped → next call rebuilds


@pytest.mark.asyncio
async def test_keyframe_count_cap_stops_capturing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "browser_keyframe_max_per_turn", 1)
    kf = KeyframeTracker()
    session = _FakeSession(
        BrowserCommandResult(ok=True, data={"final_url": "https://x/", "title": "T"}, frame=b"\xff\xd8x")
    )
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session, keyframes=kf))
    first = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    second = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert first.display.get("frame") == "browser/step-0001.jpg"
    assert "frame" not in second.display  # over per-turn cap → no more frames
    assert "上限" in json.loads(second.output).get("note", "")


@pytest.mark.asyncio
async def test_keyframe_size_cap_skips_oversized_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "browser_keyframe_max_bytes", 4)
    session = _FakeSession(
        BrowserCommandResult(ok=True, data={"final_url": "https://x/", "title": "T"}, frame=b"\xff\xd8oversized")
    )
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert result.success and "frame" not in result.display
    assert "大小上限" in json.loads(result.output).get("note", "")


@pytest.mark.asyncio
async def test_navigate_missing_frame_succeeds_with_honest_note(tmp_path):
    """Case C: want_frame but frame is None → navigate stays ok, note warns against pixels."""
    session = _FakeSession(
        BrowserCommandResult(
            ok=True,
            data={"final_url": "https://example.com/", "title": "Example", "http_status": 200},
            frame=None,
        )
    )
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({"url": "https://example.com/"}, _ctx(tmp_path))
    assert result.success
    assert "frame" not in (result.display or {})
    payload = json.loads(result.output)
    note = payload.get("note") or ""
    assert "未截到画面" in note
    assert "snapshot" in note.lower() or "browser_snapshot" in note


@pytest.mark.asyncio
async def test_screenshot_missing_frame_is_weak_failure(tmp_path):
    """Case C: browser_screenshot without a frame must not mark success."""
    session = _FakeSession(
        BrowserCommandResult(
            ok=True,
            data={"final_url": "https://example.com/", "title": "Example"},
            frame=None,
        )
    )
    tool = BrowserScreenshotTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({}, _ctx(tmp_path))
    assert result.success is False
    assert "未截到画面" in (result.output or "")
    assert (result.metadata or {}).get("code") == "no_frame"


@pytest.mark.asyncio
async def test_missing_url_is_rejected(tmp_path):
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=_FakeSession()))
    result = await tool.execute({}, _ctx(tmp_path))
    assert not result.success and "url" in result.output


@pytest.mark.asyncio
async def test_type_password_blocked_maps_to_tool_result(tmp_path):
    """Driver password hard-reject → metadata.code=password_blocked, no fill semantics."""
    session = _FakeSession(
        BrowserCommandResult(
            ok=False,
            data={},
            error="ValueError: password_blocked: AI 不得填写密码框",
        )
    )
    tool = BrowserTypeTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({"ref": "e1", "text": "secret"}, _ctx(tmp_path))
    assert result.success is False
    assert result.contract_failure is True
    assert result.metadata.get("code") == "password_blocked"
    assert "escalate" in (result.output or "")
    assert "browser_login" in (result.output or "")
    assert session.sent and session.sent[0].action == "type"


def test_browser_type_schema_guides_password_escalate():
    desc = BrowserTypeTool().schema.description
    assert "password_blocked" in desc or "password" in desc.lower()
    assert "browser_login" in desc
    assert "M0 不支持登录" not in desc


# -- 甲/乙：本会话 HTML 相对路径 ------------------------------------------------
def test_navigate_schema_mentions_workspace_relative_path():
    schema = BrowserNavigateTool().schema
    assert "相对" in schema.description or "site/index.html" in schema.description
    url_desc = schema.parameters["properties"]["url"]["description"]
    assert "相对" in url_desc or "site/index.html" in url_desc
    assert "file://" in url_desc or "file://" in schema.description


@pytest.mark.asyncio
async def test_sandbox_relative_path_fails_honestly_no_fake_success(tmp_path):
    """乙：云端沙箱相对路径 → ToolResult 失败，引导完整预览；不派发 driver。"""
    session = _FakeSession(
        BrowserCommandResult(ok=True, data={"final_url": "https://x/", "title": "T"})
    )
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({"url": "site/index.html"}, _ctx(tmp_path))
    assert result.success is False
    assert "完整预览" in (result.output or "")
    assert session.sent == []


@pytest.mark.asyncio
async def test_sandbox_workspace_url_fails_honestly(tmp_path):
    session = _FakeSession(
        BrowserCommandResult(ok=True, data={"final_url": "https://x/", "title": "T"})
    )
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session))
    result = await tool.execute(
        {"url": "workspace://c1/site/index.html"}, _ctx(tmp_path)
    )
    assert result.success is False
    assert "完整预览" in (result.output or "")
    assert session.sent == []


@pytest.mark.asyncio
async def test_sandbox_file_url_rejected(tmp_path):
    session = _FakeSession()
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({"url": "file:///tmp/x.html"}, _ctx(tmp_path))
    assert result.success is False
    assert session.sent == []


@pytest.mark.asyncio
async def test_local_relative_path_rewritten_to_workspace(tmp_path):
    """甲：local backend 相对路径 → 改写为 workspace:// 再派发。"""
    session = _FakeSession(
        BrowserCommandResult(
            ok=True,
            data={
                "final_url": "workspace://conv-id/site/index.html",
                "title": "Index",
                "http_status": None,
            },
            frame=b"\xff\xd8\xff",
        )
    )
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=session))
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
        conversation_id="Conv-ID",
    )
    result = await tool.execute({"url": "site/index.html"}, ctx)
    assert result.success, result.output
    assert session.sent
    assert session.sent[0].args["url"] == "workspace://conv-id/site/index.html"


def test_classify_and_rewrite_navigate_targets():
    from agentcore.runtime.browser.navigate_target import (
        classify_navigate_target,
        rewrite_local_navigate_url,
    )

    assert classify_navigate_target("https://example.com/") == "http"
    assert classify_navigate_target("workspace://c1/a.html") == "workspace"
    assert classify_navigate_target("site/index.html") == "relative"
    assert classify_navigate_target("file:///tmp/x") == "invalid"
    assert classify_navigate_target("../secret") == "invalid"
    assert (
        rewrite_local_navigate_url("site/index.html", "Conv-ID")
        == "workspace://conv-id/site/index.html"
    )
    assert (
        rewrite_local_navigate_url("https://example.com/", "c1")
        == "https://example.com/"
    )
