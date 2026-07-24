"""Tests for ``<workspace_context>`` environment-facts injection."""

from agentcore.runtime.context.workspace_context import (
    build_workspace_context,
    desktop_client_can_bind,
)
from agentcore.runtime.resolve.prompt import assemble_system_prompt


class _FakeBackend:
    def __init__(self, location: str, root_label: str = "workspace", *, channel=None) -> None:
        self.location = location
        self.root_label = root_label
        if channel is not None:
            self._channel = channel


def test_desktop_client_can_bind_only_electron():
    assert desktop_client_can_bind(None) is True
    assert desktop_client_can_bind("desktop") is True
    assert desktop_client_can_bind("mobile") is False
    assert desktop_client_can_bind("mobile-web") is False
    assert desktop_client_can_bind("admin") is False


def test_cloud_scratch_facts():
    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=True,
        code_execute_enabled=False,
        terminal_enabled=False,
    )
    assert out.startswith("<workspace_context>")
    assert "执行位置：云端沙箱" in out
    assert "云端临时空间" in out
    assert "触达不了用户的电脑" in out
    assert "bind_local_folder" in out
    assert "立即" in out and "勿用纯文本" in out
    assert "在哪工作" in out
    assert "仅新建会话" in out
    assert "本会话发绑定卡" in out
    assert "勿引导用户去设置改模式" in out
    assert "不可改绑" not in out
    assert "严禁引导" not in out
    assert "本机草稿" in out
    assert "code_execute=未装配" in out
    assert "terminal=未装配" in out
    # 产物出口纠偏：文件在云端、可在「文件」面板查看/下载；禁止再引导用户去本机「双击打开」
    assert "产物出口" in out
    assert "不在用户本机" in out
    assert "双击打开" in out


def test_local_remote_channel_facts():
    out = build_workspace_context(
        _FakeBackend("local", root_label="MyProject", channel=object()),
        desktop_online=True,
        code_execute_enabled=True,
        terminal_enabled=True,
    )
    assert "执行位置：用户本机（经桌面通道遥控）" in out
    assert "本地目录（根标签 `MyProject`）" in out
    assert "code_execute=已装配" in out
    assert "terminal=已装配" in out
    assert "bind_local_folder" not in out  # already local — no bind nudge
    assert "产物出口" in out  # 产物出口事实对本地会话同样注入


def test_sidecar_local_without_channel():
    out = build_workspace_context(
        _FakeBackend("local"),
        desktop_online=True,
        code_execute_enabled=True,
        terminal_enabled=True,
    )
    assert "本机引擎 / sidecar" in out


def test_mobile_session_omits_bind_nudge():
    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=False,
        code_execute_enabled=False,
        terminal_enabled=False,
    )
    assert "桌面端不在线" in out
    assert "bind_local_folder" not in out


def test_assemble_system_prompt_includes_workspace_facts():
    facts = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=True,
        code_execute_enabled=False,
        terminal_enabled=False,
    )
    prompt = assemble_system_prompt(workspace_context=facts)
    assert "<workspace_context>" in prompt
    assert "云端沙箱" in prompt
    # Without facts, no block (prefix-cache identity for catalog / bare tests).
    bare = assemble_system_prompt()
    assert "<workspace_context>" not in bare
