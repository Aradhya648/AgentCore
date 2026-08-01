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
    BROWSER_TOOL_NAMES,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registration import (
    AUDIENCE_BOTH,
    AUDIENCE_WORKER_ONLY,
    ToolSurface,
    tool_registration,
)
from agentcore.tools.sandbox.browser.netns import (
    EGRESS_UNAVAILABLE_CODE,
    browser_netns_health,
    set_browser_netns_health_for_tests,
)
from agentcore.tools.sandbox.browser.protocol import (
    BrowserCommandResult,
    BrowserDriverCrashedError,
    BrowserSessionAcquireError,
    BrowserSessionError,
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


def _fail_text(result) -> str:
    """Browser failures put the message in ``error`` only (avoid output+error double)."""
    return (result.error or result.output or "")


# -- governance (D11 五维) ------------------------------------------------------
def test_navigate_is_builtin_both():
    reg = tool_registration(BrowserNavigateTool)
    schema = BrowserNavigateTool().schema
    assert reg.surface is ToolSurface.BUILTIN
    assert reg.audience == AUDIENCE_BOTH
    assert reg.execution_class is True
    assert reg.browser_class is True
    assert schema.approval is ToolApproval.GRANTABLE
    assert schema.category is ToolCategory.EXECUTION


def test_interactive_browser_tools_are_builtin_both():
    from agentcore.tools.builtin.browser import (
        BrowserClickTool,
        BrowserScrollTool,
        BrowserSnapshotTool,
        BrowserTypeTool,
    )

    for cls in (BrowserClickTool, BrowserTypeTool, BrowserScrollTool, BrowserSnapshotTool):
        reg = tool_registration(cls)
        schema = cls().schema
        assert reg.surface is ToolSurface.BUILTIN, schema.name
        assert reg.audience == AUDIENCE_BOTH, schema.name
        assert reg.browser_class and reg.execution_class
        assert schema.approval is ToolApproval.GRANTABLE


def test_screenshot_remains_worker_only():
    reg = tool_registration(BrowserScreenshotTool)
    schema = BrowserScreenshotTool().schema
    assert reg.surface is ToolSurface.WORKER_ONLY
    assert reg.audience == AUDIENCE_WORKER_ONLY
    assert reg.browser_class and reg.execution_class
    assert schema.approval is ToolApproval.GRANTABLE


def test_ceo_registry_holds_interactive_browser_when_include_browser():
    from agentcore.tools.builtin import build_ceo_tool_registry

    off = {s.name for s in build_ceo_tool_registry().list_all()}
    assert "browser_navigate" not in off
    assert not (_BROWSER_NAMES & off)

    on = {s.name for s in build_ceo_tool_registry(include_browser=True).list_all()}
    assert (_BROWSER_NAMES & on) == (_BROWSER_NAMES - {"browser_screenshot"})
    assert "browser_screenshot" not in on
    assert build_ceo_tool_registry(include_browser=True).get(
        "browser_navigate"
    ).schema.approval is ToolApproval.GRANTABLE
    assert build_ceo_tool_registry(include_browser=True).get(
        "browser_click"
    ).schema.approval is ToolApproval.GRANTABLE


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


def test_gate_withholds_when_browser_netns_unhealthy(tmp_path, monkeypatch):
    """Cloud sandbox ok but netns capability False → do not assemble browser_*."""
    backend = _server_backend(tmp_path)
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    set_browser_netns_health_for_tests(False)
    assert browser_execution_enabled_for(backend) is False


def test_gate_netns_unprobed_keeps_cloud_health_semantics(tmp_path, monkeypatch):
    """None netns health + cloud healthy → still True (tests / unbooted compatibility)."""
    backend = _server_backend(tmp_path)
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    assert browser_netns_health() is None
    assert browser_execution_enabled_for(backend) is True


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
        acquire_error: Exception | None = None,
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
async def test_type_success_returns_current_snapshot_version(tmp_path):
    """Mutation success must surface bumped snapshot_version (same field as snapshot)."""
    from agentcore.tools.builtin.browser import BrowserClickTool

    session = _FakeSession(
        BrowserCommandResult(
            ok=True,
            data={
                "final_url": "https://example.com/",
                "title": "Example",
                "snapshot_version": 3,
            },
            frame=b"\xff\xd8\xff\xe0jpeg",
        )
    )
    tool = BrowserTypeTool(registry=_FakeRegistry(session=session))
    result = await tool.execute(
        {"ref": "e1", "text": "hello", "snapshot_version": 2}, _ctx(tmp_path)
    )
    assert result.success
    payload = json.loads(result.output)
    assert payload["snapshot_version"] == 3
    assert payload["action"] == "type"

    click = BrowserClickTool(registry=_FakeRegistry(session=session))
    clicked = await click.execute({"ref": "e2", "snapshot_version": 3}, _ctx(tmp_path))
    assert clicked.success
    assert json.loads(clicked.output)["snapshot_version"] == 3


@pytest.mark.asyncio
async def test_ref_stale_error_is_not_doubled(tmp_path):
    """Driver ValueError + host prefix must not appear twice in model-facing text."""
    from agentcore.tools.builtin.browser import BrowserClickTool

    session = _FakeSession(
        BrowserCommandResult(
            ok=False,
            error="ValueError: ref 版本过期（快照 v1 ≠ 当前 v2）：页面已变化，请重新 browser_snapshot 获取最新 ref",
        )
    )
    tool = BrowserClickTool(registry=_FakeRegistry(session=session))
    result = await tool.execute({"ref": "e1", "snapshot_version": 1}, _ctx(tmp_path))
    assert not result.success
    text = _fail_text(result)
    assert text.count("ref 版本过期") == 1
    assert "ValueError:" not in text
    assert result.output == ""


@pytest.mark.asyncio
async def test_busy_returns_explainable_failure(tmp_path):
    tool = BrowserNavigateTool(registry=_FakeRegistry(busy=True))
    result = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert not result.success and "已满" in _fail_text(result)


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
async def test_egress_unavailable_retires_all_browser_tools(tmp_path):
    """NetnsError / egress hard-fail: one shot → retire whole browser_* surface."""
    tool = BrowserNavigateTool(
        registry=_FakeRegistry(
            acquire_error=BrowserSessionError(
                "云端浏览器沙箱网络隔离不可用（netns 创建失败）",
                code=EGRESS_UNAVAILABLE_CODE,
            )
        )
    )
    result = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert not result.success
    assert (result.metadata or {}).get("code") == EGRESS_UNAVAILABLE_CODE
    assert set(result.metadata.get("retire_tools") or []) == BROWSER_TOOL_NAMES
    assert "retire_message" in (result.metadata or {})
    assert "web_search" in _fail_text(result) and "browser_" in _fail_text(result)
    # No double「浏览器会话启动失败」prefix on the classified path.
    assert _fail_text(result).count("浏览器会话启动失败") == 0
    # Sticky: next turn's assembly gate must see netns as unavailable.
    assert browser_netns_health() is False


@pytest.mark.asyncio
async def test_egress_unavailable_from_wrapped_netns_message(tmp_path):
    """Legacy wrapped NetnsError string still classifies without an explicit code."""
    tool = BrowserNavigateTool(
        registry=_FakeRegistry(
            acquire_error=BrowserSessionError(
                "浏览器会话启动失败：NetnsError: ip netns add acbrw0 failed (1): "
                "mkdir /run/netns failed: Permission denied"
            )
        )
    )
    result = await tool.execute({"url": "https://x/"}, _ctx(tmp_path))
    assert not result.success
    assert (result.metadata or {}).get("code") == EGRESS_UNAVAILABLE_CODE
    assert set(result.metadata.get("retire_tools") or []) == BROWSER_TOOL_NAMES
    assert browser_netns_health() is False


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
    assert "页面状态已丢失" in _fail_text(result) and "重新开始" in _fail_text(result)
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
    assert "未截到画面" in _fail_text(result)
    assert (result.metadata or {}).get("code") == "no_frame"


@pytest.mark.asyncio
async def test_missing_url_is_rejected(tmp_path):
    tool = BrowserNavigateTool(registry=_FakeRegistry(session=_FakeSession()))
    result = await tool.execute({}, _ctx(tmp_path))
    assert not result.success and "url" in _fail_text(result)


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
    assert "escalate" in _fail_text(result)
    assert "browser_login" in _fail_text(result)
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
    assert "完整预览" in _fail_text(result)
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
    assert "完整预览" in _fail_text(result)
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
