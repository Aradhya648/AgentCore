"""Tests for ``<workspace_context>`` environment-facts injection."""

from agentcore.runtime.context.workspace_context import (
    build_workspace_context,
    desktop_client_can_bind,
    resolve_channel_profile,
)
from agentcore.runtime.resolve.prompt import assemble_system_prompt
from agentcore.tools.builtin import build_ceo_tool_registry


class _FakeBackend:
    def __init__(self, location: str, root_label: str = "workspace", *, channel=None) -> None:
        self.location = location
        self.root_label = root_label
        if channel is not None:
            self._channel = channel


def test_desktop_client_can_bind_fail_closed():
    assert desktop_client_can_bind(None) is False
    assert desktop_client_can_bind("") is False
    assert desktop_client_can_bind("desktop") is True
    assert desktop_client_can_bind("web") is False
    assert desktop_client_can_bind("mobile") is False
    assert desktop_client_can_bind("mobile-web") is False
    assert desktop_client_can_bind("android") is False
    assert desktop_client_can_bind("admin") is False


def test_resolve_channel_profile_fail_closed_and_surfaces():
    unknown = resolve_channel_profile(None)
    assert unknown.surface == "unknown"
    assert unknown.desktop_online is False
    assert unknown.can_bind_folder is False

    blank = resolve_channel_profile("  ")
    assert blank.surface == "unknown"
    assert blank.desktop_online is False

    desktop = resolve_channel_profile("desktop")
    assert desktop.surface == "desktop"
    assert desktop.desktop_online is True
    assert desktop.can_bind_folder is True

    web = resolve_channel_profile("web")
    assert web.surface == "web"
    assert web.desktop_online is False
    assert web.can_bind_folder is False

    mobile_web = resolve_channel_profile("mobile-web")
    assert mobile_web.surface == "web"
    assert mobile_web.desktop_online is False

    mobile = resolve_channel_profile("mobile")
    assert mobile.surface == "mobile"
    assert mobile.desktop_online is False

    android = resolve_channel_profile("android")
    assert android.surface == "mobile"
    assert android.can_bind_folder is False

    # Unknown tokens fail closed (do not legacy-default to desktop).
    admin = resolve_channel_profile("admin")
    assert admin.surface == "unknown"
    assert admin.desktop_online is False


def test_web_and_missing_header_ceo_registry_omits_host():
    """Acceptance: web / missing header → no host_* on CEO registry (web-safe)."""
    web_names = {s.name for s in build_ceo_tool_registry(desktop_online=False).list_all()}
    assert not any(n.startswith("host_") for n in web_names)

    # Profile wiring: web / None → desktop_online False → same roster.
    assert resolve_channel_profile("web").desktop_online is False
    assert resolve_channel_profile(None).desktop_online is False
    missing = {
        s.name
        for s in build_ceo_tool_registry(
            desktop_online=resolve_channel_profile(None).desktop_online
        ).list_all()
    }
    assert not any(n.startswith("host_") for n in missing)

    desktop_names = {
        s.name
        for s in build_ceo_tool_registry(
            desktop_online=resolve_channel_profile("desktop").desktop_online
        ).list_all()
    }
    assert any(n.startswith("host_") for n in desktop_names)

def test_cloud_scratch_facts():
    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=True,
        code_execute_enabled=False,
        terminal_enabled=False,
    )
    assert out.startswith("<workspace_context>")
    assert "执行位置：云端沙箱" in out
    assert "云端草稿/临时文件空间" in out
    assert "不是用户本机目录" in out
    assert "不是用户本机已打开的仓库" in out
    assert "空树" in out
    assert "本机空项目" in out or "宿主机器" in out
    assert "触达不了用户的电脑" not in out
    assert "本机 Host" in out or "host=" in out
    assert "host=已装配" in out
    assert "bind_local_folder" in out
    assert "open_local_project" in out
    assert "grant_readonly_folder" in out
    assert "grant_organize_folder" in out
    assert "与工作区绑定正交" in out
    assert "区外目录授权需先处在本地工作区" not in out
    assert "云端无法直接授权本机区外路径" not in out
    assert "立即" in out and "勿用纯文本" in out
    assert "在哪工作" in out
    assert "仅新建会话" in out
    assert "ask_user" in out  # 本机出路走卡，勿纯文本
    assert "≠打开项目" in out or "禁止用 bind 冒充" in out
    assert "勿引导用户去设置改模式" in out
    # 定案 A：优化项目 ≠ 默认催开项目；附件收窄范围时先干活。
    assert "≠默认开项目卡" in out or "收窄本轮" in out
    assert "开工前置" in out
    assert "不可改绑" not in out
    assert "严禁引导" not in out
    assert "本机草稿" in out
    assert "本会话发绑定卡" not in out  # 旧口径：已改为意图分流
    assert "code_execute=未装配" in out
    assert "terminal=未装配" in out
    assert "browser=未装配" in out
    assert "local_open=未装配" in out
    assert "host=已装配" in out
    # 产物出口纠偏：文件在云端、「完整预览」进右坞浏览器；禁止本机「双击打开」
    assert "产物出口" in out
    assert "不在用户本机" in out
    assert "完整预览" in out
    assert "右坞「浏览器」" in out or "右坞" in out
    assert "双击打开" in out
    assert "浏览器指引" in out
    assert "browser=未装配" in out
    assert "勿假装" in out or "勿调用 browser_*" in out
    assert "host_info" in out or "host_audio" in out or "本机 Host 指引" in out
    # 旧「云端临时空间」短标签已换成诚实草稿口径
    assert "工作区身份：云端临时空间" not in out
    # 案卷布局（始终可见）：三行出口 + 边界
    assert "案卷出口·调研/讨论：`AgentCore/文档/research/`" in out
    assert "案卷出口·辩论副产物：`AgentCore/文档/debate/`" in out
    assert "案卷出口·审查：`AgentCore/文档/reviews/`" in out
    assert "讨论/调研/审查类交付写此树" in out
    assert "用户工程源码仍写业务路径" in out
    assert "通常无 Git" in out
    assert "no_repo" in out


def test_cloud_host_off_capability():
    from agentcore.core.types import HostAxis

    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=True,
        code_execute_enabled=False,
        terminal_enabled=False,
        host_axis=HostAxis.OFF,
    )
    assert "host=未装配" in out
    assert "host=off" in out or "本机协助" in out or "勿调用 host_*" in out


def test_no_desktop_host_unassembled():
    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=False,
        code_execute_enabled=False,
        terminal_enabled=False,
    )
    assert "host=未装配" in out
    assert "无桌面回填通道" in out or "勿假装" in out


def test_local_remote_channel_facts():
    out = build_workspace_context(
        _FakeBackend("local", root_label="MyProject", channel=object()),
        desktop_online=True,
        code_execute_enabled=True,
        terminal_enabled=True,
        browser_enabled=False,
    )
    assert "执行位置：用户本机（经桌面通道遥控）" in out
    assert "本地目录（根标签 `MyProject`）" in out
    assert "code_execute=已装配" in out
    assert "terminal=已装配" in out
    assert "browser=未装配" in out
    assert "local_open=已装配" in out
    assert "bind_local_folder" not in out  # already local — no bind nudge
    assert "产物出口" in out  # 产物出口事实对本地会话同样注入
    # 已绑定本地工程：「打开项目」=跑当前，换目录才 open_local_project
    assert "已绑定本地工程" in out
    assert "跑当前项目" in out
    assert "open_local_project" in out


def test_browser_capability_override():
    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=True,
        code_execute_enabled=True,
        terminal_enabled=False,
        browser_enabled=True,
    )
    assert "browser=已装配" in out
    assert "local_open=未装配" in out
    assert "escalate(browser_login=true)" in out
    assert "接管登录" in out
    assert "browser_navigate" in out
    assert "禁止为此" in out or "勿为此" in out or "你自己" in out
    assert "禁止只用 read_url" in out or "假装已打开" in out
    assert "browser_open" in out  # 明示禁编造
    # 意图梯度：navigate 成功即可；验收/截图才 snapshot；跑起来≠必须 navigate
    assert "navigate 成功" in out or "即可收工" in out
    assert "验收" in out and "截图" in out
    assert "≠必须 navigate" in out or "跑起来" in out
    # CEO 可直持 navigate；其余 browser_* 仍 worker
    assert "CEO 可直持" in out or "navigate 由 CEO" in out
    assert "仅 worker" in out
    # 乙：沙箱已装配时仍标明相对路径不可测 / 完整预览
    assert "相对" in out or "完整预览" in out
    assert "http(s)" in out or "公网" in out


def test_local_browser_guide_mentions_workspace_relative_path():
    """甲：本机 + browser 已装配 → 指引相对路径与完整预览同源。"""
    out = build_workspace_context(
        _FakeBackend("local"),
        desktop_online=True,
        code_execute_enabled=True,
        terminal_enabled=True,
        browser_enabled=True,
    )
    assert "browser=已装配" in out
    assert "site/index.html" in out or "相对" in out
    assert "完整预览" in out or "workspace://" in out
    assert "file://" in out  # 明示不支持


def test_browser_unassembled_guide_mentions_bind_or_sandbox():
    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=True,
        code_execute_enabled=False,
        terminal_enabled=False,
        browser_enabled=False,
    )
    assert "浏览器指引" in out
    assert (
        "bind_local_folder" in out
        or "open_local_project" in out
        or "云端沙箱浏览器" in out
    )
    assert "escalate(browser_login=true)" in out
    assert "已登录，继续" in out
    assert "Cookie" in out  # 明确否决扫 Cookie 冒充路径
    assert "用浏览器打开" in out
    assert "非右坞浏览器" in out
    assert "静默" in out or "假装" in out


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
    assert "桌面回填通道未连接" in out
    # Must not accuse a device form when the channel is merely offline / fail-closed.
    assert "Web / 移动端" not in out
    assert "Web / 手机" not in out
    assert "当前为 Web" not in out
    assert "勿将通道缺失说成用户在用 Web/手机" in out
    assert "区外目录授权仅桌面端可用" in out
    assert "https://fashitianxia.xyz/download" in out
    assert "官方桌面客户端" in out
    assert "勿发 grant_* / bind_local_folder / open_local_project" in out
    # 禁止语里可点名 action；不得写成可履约的 action= 分流广告
    assert "action=bind_local_folder" not in out
    assert "action=grant_readonly_folder" not in out
    assert "action=open_local_project" not in out
    assert "立即发卡" not in out
    assert "与工作区绑定正交" not in out
    assert "授权已确认" in out  # 铁律禁语
    assert "本对话尚无会话级区外目录授权" in out
    assert "本对话已授权区外目录：" not in out  # 无挂载不得声称已授权状态行


def test_no_mounts_forbids_claiming_grant_confirmed():
    """未见 external 挂载行时，prompt 须禁止「授权已确认」。"""
    out = build_workspace_context(
        _FakeBackend("server"),
        desktop_online=False,
        code_execute_enabled=False,
        terminal_enabled=False,
    )
    assert "本对话尚无会话级区外目录授权" in out
    assert "本对话已授权区外目录：" not in out
    assert "禁止说「授权已确认」" in out or (
        "禁止说" in out and "授权已确认" in out
    )


def test_cloud_desktop_online_allows_external_grant_without_bind():
    """W3 正交：云端 scratch + 桌面在线 → 可直接 grant，勿要求先 bind。"""
    out = build_workspace_context(
        _FakeBackend("server", root_label="conv:x"),
        desktop_online=True,
        code_execute_enabled=False,
        terminal_enabled=False,
    )
    assert "执行位置：云端沙箱" in out
    assert "grant_readonly_folder" in out
    assert "与工作区绑定正交" in out
    assert "看桌面" in out or "本机某目录" in out
    assert "手填绝对路径" in out or "探主机家目录" in out
    assert "区外目录授权需先处在本地工作区" not in out


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
