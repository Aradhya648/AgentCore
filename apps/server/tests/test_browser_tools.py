"""Browser tools: D11 governance five-dim, cloud-only gate, execute + keyframe caps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentcore.config import settings
from agentcore.core.types import PermissionPreset, ToolApproval, ToolCategory
from agentcore.runtime.browser.keyframes import KeyframeTracker
from agentcore.tools.builtin import browser_execution_enabled_for, build_worker_registry
from agentcore.tools.builtin.browser import (
    BROWSER_TOOL_CLASSES,
    BrowserNavigateTool,
    BrowserSnapshotTool,
    BrowserTypeTool,
)
from agentcore.tools.protocol import ToolContext
from agentcore.tools.registration import AUDIENCE_WORKER_ONLY, ToolSurface, tool_registration
from agentcore.tools.sandbox.browser.protocol import (
    BrowserCommandResult,
    BrowserDriverCrashedError,
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


# -- cloud-only gate -----------------------------------------------------------
def _server_backend(tmp_path: Path) -> ServerWorkspace:
    return ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())


def test_gate_requires_server_plus_gvisor_plus_health(tmp_path, monkeypatch):
    backend = _server_backend(tmp_path)
    assert browser_execution_enabled_for(None) is False
    assert browser_execution_enabled_for(LocalBackend()) is False  # local: not M0
    monkeypatch.setattr(settings, "gvisor_enabled", False)
    assert browser_execution_enabled_for(backend) is False  # no gVisor isolation
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    assert browser_execution_enabled_for(backend) is True
    set_cloud_sandbox_health_for_tests(False)
    assert browser_execution_enabled_for(backend) is False  # probe says unhealthy


def test_worker_registry_includes_browser_only_on_gvisor_cloud(tmp_path, monkeypatch):
    backend = _server_backend(tmp_path)
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    names = {s.name for s in build_worker_registry(backend=backend).list_all()}
    assert names >= _BROWSER_NAMES

    # OBSERVE withholds the whole execution class (browser included).
    observe = {
        s.name
        for s in build_worker_registry(
            backend=backend, permission_preset=PermissionPreset.OBSERVE
        ).list_all()
    }
    assert not (_BROWSER_NAMES & observe)


def test_worker_registry_excludes_browser_without_gvisor(tmp_path, monkeypatch):
    backend = _server_backend(tmp_path)
    monkeypatch.setattr(settings, "gvisor_enabled", False)
    names = {s.name for s in build_worker_registry(backend=backend).list_all()}
    assert not (_BROWSER_NAMES & names)


def test_worker_registry_excludes_browser_on_local(monkeypatch):
    monkeypatch.setattr(settings, "gvisor_enabled", True)
    set_cloud_sandbox_health_for_tests(True)
    names = {s.name for s in build_worker_registry(backend=LocalBackend()).list_all()}
    assert not (_BROWSER_NAMES & names)


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
    def __init__(self, session=None, keyframes=None, busy=False, taken_over=False):
        self._session = session
        self._keyframes = keyframes or KeyframeTracker()
        self._busy = busy
        self._taken_over = taken_over
        self.closed: list[str] = []

    def is_taken_over(self, cid):
        # M2 接管互斥: the tool consults this before acquiring; default False (no takeover).
        return self._taken_over

    async def acquire(self, request):
        if self._busy:
            raise BrowserSessionsBusyError("云端浏览器会话已满")
        return self._session, self._keyframes

    async def close(self, cid):
        self.closed.append(cid)


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
