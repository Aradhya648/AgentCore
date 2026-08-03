"""Per-turn ``<workspace_context>`` — structured environment facts for CEO and workers.

根治「模型环境盲」：每回合把执行位置、工作区身份、桌面通道、本回合可执行能力写成显式
事实块注入 system prompt，避免 CEO 在云端 scratch 上规划「打开本机软件」并空跑委派。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from agentcore.workspace.stage_dirs import DEBATE_DIR, RESEARCH_DIR, REVIEWS_DIR

if TYPE_CHECKING:
    from agentcore.core.types import HostAxis
    from agentcore.workspace.protocol import WorkspaceBackend

ChannelSurface = Literal["desktop", "web", "mobile", "unknown"]

_WEB_SURFACES: frozenset[str] = frozenset({"web", "mobile-web"})
_MOBILE_SURFACES: frozenset[str] = frozenset({"mobile", "android", "ios"})


@dataclass(frozen=True)
class ChannelProfile:
    """Single source for channel capabilities derived from ``X-Client-Platform``.

    Orthogonal to workspace ``location`` (local/server) and to auth audience
    (``parse_client_platform`` may still legacy-default desktop for login aud).
    Missing / unknown headers fail closed — never pretend the web can drive Host.
    """

    surface: ChannelSurface
    desktop_online: bool
    can_bind_folder: bool


def resolve_channel_profile(x_client_platform: str | None) -> ChannelProfile:
    """Map raw ``X-Client-Platform`` → :class:`ChannelProfile` (fail-closed).

    Only explicit ``desktop`` is a fulfillable desktop channel. Absent / blank /
    unknown values → ``surface=unknown``, both capability flags ``False``.
    """
    raw = (x_client_platform or "").strip().lower()
    if not raw:
        return ChannelProfile(surface="unknown", desktop_online=False, can_bind_folder=False)
    if raw == "desktop":
        return ChannelProfile(surface="desktop", desktop_online=True, can_bind_folder=True)
    if raw in _WEB_SURFACES:
        return ChannelProfile(surface="web", desktop_online=False, can_bind_folder=False)
    if raw in _MOBILE_SURFACES:
        return ChannelProfile(surface="mobile", desktop_online=False, can_bind_folder=False)
    return ChannelProfile(surface="unknown", desktop_online=False, can_bind_folder=False)


def desktop_client_can_bind(x_client_platform: str | None) -> bool:
    """Thin fail-closed wrapper: folder AskOption actions need a desktop client.

    Covers ``open_local_project`` / ``bind_local_folder`` / ``grant_*``. ``None`` /
    unknown → ``False`` (unlike auth ``parse_client_platform``, which may legacy-
    default desktop for JWT aud).
    """
    return resolve_channel_profile(x_client_platform).can_bind_folder


def build_workspace_context(
    backend: WorkspaceBackend | None,
    *,
    desktop_online: bool,
    code_execute_enabled: bool | None = None,
    terminal_enabled: bool | None = None,
    browser_enabled: bool | None = None,
    exec_languages: list[str] | tuple[str, ...] | None = None,
    host_axis: HostAxis | str | None = None,
    mcp_enabled: bool = False,
    mcp_label: str | None = None,
) -> str:
    """Render the ``<workspace_context>`` block for this turn's backend + client.

    Always returns a non-empty block when ``backend`` is set (environment is a fact,
    even for an empty cloud scratch). ``backend is None`` → ``""`` (caller omits).

    Capability line uses the same predicates as worker registry assembly
    (``code_execution_enabled_for`` / ``browser_execution_enabled_for``); optional
    ``*_enabled`` overrides are for tests / probes only — not a second truth source.

    ``exec_languages`` is the probed (local/sidecar) or fixed (cloud) language
    surface advertised on ``code_execute``; when set and execution is on, a one-line
    interpreter fact is appended so the model never plans against a missing launcher.
    """
    if backend is None:
        return ""

    location: Literal["server", "local"] = backend.location
    root_label = (getattr(backend, "root_label", None) or "workspace").strip() or "workspace"
    # Sidecar reuses ServerWorkspace(location=local) with direct Path I/O; LocalWorkspace
    # is the remote desktop-channel path. Both are "用户本机" for the model.
    is_local = location == "local"
    channel = getattr(backend, "_channel", None)
    is_remote_local = is_local and channel is not None

    if is_local:
        location_line = (
            "执行位置：用户本机"
            + ("（经桌面通道遥控）" if is_remote_local else "（本机引擎 / sidecar）")
        )
        identity_line = f"工作区身份：本地目录（根标签 `{root_label}`）"
        reach_line = "本机应用、本机文件与本机终端均可按已装配工具触达。"
        artifact_line = (
            "产物出口：你写入工作区的文件位于用户本机目录，"
            "用户可在「文件」面板查看；HTML 同样走「完整预览」进右坞「浏览器」标签"
            "（或本机直接打开，按用户习惯）。"
        )
    else:
        location_line = "执行位置：云端沙箱（服务端）"
        # 裸聊默认云 scratch：空树 ≠ 本机/已打开仓库。对模型显式纠偏，避免把宿主路径当项目。
        identity_line = (
            f"工作区身份：本会话云端草稿/临时文件空间（根标签 `{root_label}`）——"
            "不是用户本机目录，也不是用户本机已打开的仓库或项目工作区。"
        )
        # Host 定案 §3.4: 云 reach 与 host= 正交——工作区在云；本机 Host 以能力行为准。
        reach_line = (
            "云端工作区文件在云端沙箱，不是用户本机磁盘；"
            "本机 Host（音响/系统信息/打开设置等）另计，以能力行 host= 为准——"
            "host=已装配时可经桌面回填通道调用 host_*；"
            "host=未装配时勿假装已查本机、勿假设能打开或安装用户机器上的软件；"
            "空树只表示本会话云端草稿尚无文件，勿当成「本机空项目」或宿主机器上的 Git 仓库。"
        )
        artifact_line = (
            "产物出口：你写入工作区的文件保存在云端工作区（不在用户本机），"
            "用户可在桌面端「文件」面板查看与下载；"
            "HTML 完整效果请指引用户点产物卡或文件横幅的「完整预览」"
            "（打开右坞「浏览器」标签，应用内渲染，非系统浏览器）；"
            "不要让用户去本机磁盘查找这些文件，"
            "也不要声称文件已在用户电脑上、或让其在本地「双击打开」。"
        )

    if desktop_online:
        grant_line = (
            "区外目录：桌面在线即可用 ask_user 选项 `action=grant_readonly_folder`"
            "（只读分析）或 `grant_organize_folder`（整理）；确认后以 "
            "`external/<别名>/…` 访问（经桌面通道、仅本次对话、可撤销）。"
            "与工作区绑定正交——不必先改绑或打开本地项目。"
            "「看桌面/看本机某目录」只走 grant_*：立即发卡，勿纯文本劝授权；"
            "禁止要用户手填绝对路径；禁止用 code_execute/terminal 探主机家目录找路径。"
        )
        if is_local:
            desktop_line = (
                "客户端通道：桌面端在线（本机执行通道可用）。"
                "已绑定本地工程：「打开项目 / 跑起来看一下」=跑当前项目"
                "（terminal 启服报 URL），勿再弹 open_local_project；"
                "仅换目录/换工程根才 `action=open_local_project`。"
            )
        else:
            desktop_line = (
                "客户端通道：桌面端在线——本机相关出路按意图分流（立即发 ask_user 卡，"
                "勿用纯文本解释或询问；完成前不要委派本机任务）："
                "① 用户要把本机目录当【本地项目】打开（仓库/工程根）→ "
                "`action=open_local_project`（新建会话挂 Folder，空 subpath；"
                "禁止改写本会话 folder_id；禁止用 bind 冒充打开项目）；"
                "② 本会话仅需本机执行环境（继续云端/裸聊 scratch）→ "
                "`action=bind_local_folder`（绑 conversations/<id>，≠打开项目）；"
                "③ 看/分析/整理本机某目录（含桌面）→ grant_*（与①②正交，勿改绑冒充）；"
                "④ 「优化/改项目」≠默认开项目卡：仅当用户要打开本机工程根才开 "
                "`open_local_project`；已有附件且用户收窄本轮范围（先这些/就这些）→ "
                "先读材料与工作区已有产物动手，勿把开项目当开工前置；"
                "「在哪工作」仅新建会话可选（快速对话=云端默认 / 本机草稿 / 项目），"
                "勿引导用户去设置改模式。"
            )
    else:
        # desktop_online=False covers missing header, unknown surface, and true
        # non-desktop clients — never accuse a device form (Web/手机) by default.
        desktop_line = (
            "客户端通道：桌面回填通道未连接——"
            "打开本地项目、本机文件夹绑定、区外目录授权均须官方桌面客户端且通道已连接，"
            "当前会话无法履约；请引导用户在桌面客户端打开本对话，或前往 "
            "https://fashitianxia.xyz/download 下载安装桌面端后再操作；"
            "勿发 grant_* / bind_local_folder / open_local_project 选项卡冒充可授权。"
        )
        grant_line = (
            "区外目录授权仅桌面端可用；当前客户端无法履行。"
            "铁律：仅当 mounts 行写明「本对话已授权区外目录…」时，才可声称已授权"
            "或可访问本机目录；尚无授权时禁止说「授权已确认」。"
        )

    mounts = getattr(backend, "_mounts", None) or {}
    if mounts:
        parts = []
        for a, m in mounts.items():
            mode = getattr(m, "mode", None) or (
                "readonly" if getattr(m, "readonly", True) else "organize"
            )
            mode_zh = "只读" if mode == "readonly" else "整理"
            parts.append(
                f"`external/{a}/`（{getattr(m, 'label', a)}，{mode_zh}）"
            )
        mounts_line = "本对话已授权区外目录：" + "；".join(parts) + "。"
    else:
        mounts_line = (
            "本对话尚无会话级区外目录授权。"
            "（未见「本对话已授权区外目录…」则禁止声称授权已确认或可访问本机目录。）"
        )

    exec_on = code_execute_enabled
    if exec_on is None:
        from agentcore.tools.builtin import code_execution_enabled_for

        exec_on = code_execution_enabled_for(backend)
    term_on = is_local if terminal_enabled is None else terminal_enabled
    browser_on = browser_enabled
    if browser_on is None:
        from agentcore.tools.builtin import browser_execution_enabled_for

        browser_on = browser_execution_enabled_for(backend)
    # local_open = 本机工作区可让用户直接打开产物（非 L3 浏览器工具；与 location 同事实）。
    local_open_on = is_local
    # Host 已装配 ⇔ host≠off ∧ 桌面回填通道可达（desktop_online）。
    host_off = False
    if host_axis is not None:
        host_val = getattr(host_axis, "value", None) or str(host_axis)
        host_off = host_val == "off"
    host_on = desktop_online and not host_off
    mcp_on = bool(mcp_enabled) if mcp_label is None else mcp_label == "已装配"
    mcp_cap = mcp_label if mcp_label is not None else ("已装配" if mcp_enabled else "未装配")
    caps: list[str] = []
    caps.append(f"code_execute={'已装配' if exec_on else '未装配'}")
    caps.append(f"terminal={'已装配' if term_on else '未装配'}")
    caps.append(f"browser={'已装配' if browser_on else '未装配'}")
    caps.append(f"local_open={'已装配' if local_open_on else '未装配'}")
    caps.append(f"host={'已装配' if host_on else '未装配'}")
    caps.append(f"mcp={mcp_cap}")
    capability_line = "本回合执行能力：" + "；".join(caps) + "。"
    if not desktop_online:
        mcp_guide_line = (
            "本机 MCP 指引：mcp=未装配（无桌面回填通道）——"
            "勿调用 mcp_*、勿假装已接本地 MCP Server；"
            "勿将通道缺失说成用户在用 Web/手机；"
            "请引导在桌面回填已连接的会话重试。"
        )
    elif mcp_on:
        mcp_guide_line = (
            "本机 MCP 指引：mcp=已装配（经桌面 stdio 回填，非云进程直连本机）。"
            "仅 worker 持 MCP 工具（一律需审批）；CEO 不直持。"
            "工具名形如 mcp_<server>_<tool>；失败时如实说明，勿编造结果。"
        )
    else:
        mcp_guide_line = (
            f"本机 MCP 指引：mcp={mcp_cap}——"
            "本回合无可用 MCP 工具（未配置 / 握手失败已降级）；"
            "勿调用 mcp_*、勿假装已接本地 MCP；纯聊不受影响。"
        )
    if host_off:
        host_guide_line = (
            "本机 Host 指引：host=未装配（用户已关本机协助 / host=off）——"
            "勿调用 host_*、勿假装已查声卡或本机系统信息；"
            "工作区 terminal / code_execute 仍可能已装配（host=off ≠ 整机只读）。"
        )
    elif host_on:
        host_guide_line = (
            "本机 Host 指引：host=已装配（经桌面回填通道，非云进程直探本机）。"
            "本机排查可先用 L1 host_info / host_audio_devices，也可直接 host_shell"
            "（短时本机命令，不必先 delegate）；结构化 host_* 仍作快捷路径。"
            "长驻进程（dev server）用 terminal，禁止 host_shell 启服。"
            "禁止用通识 FAQ 冒充已查本机；打开声音设置 / L3 动作用 worker"
            "（host_open_settings / host_audio_set_default 等）。"
        )
    else:
        host_guide_line = (
            "本机 Host 指引：host=未装配（无桌面回填通道）——"
            "勿调用 host_*、勿假装已查声卡或本机系统信息；"
            "需要本机观测时如实说明限制，可用通识或 ask_user。"
        )
    if browser_on:
        if is_local:
            path_capability = (
                "桌面 Local Bridge 可打开本会话工作区相对 HTML 路径"
                "（如 `site/index.html`，与用户「完整预览」同源 workspace://）；"
                "公网仍用完整 http(s)；不支持 file://。"
                "打开后可继续 click/type/snapshot。"
            )
        else:
            path_capability = (
                "当前为云端沙箱浏览器：仅支持公网 http(s)；"
                "本会话 HTML 相对路径不可测——请指引用户点产物「完整预览」，"
                "禁止假装已用 browser_navigate 打开工作区页。"
            )
        browser_guide_line = (
            "浏览器指引：本回合已装配 browser_*"
            "（navigate/click/type/scroll/snapshot 由 CEO 可直持；screenshot 仅 worker）。"
            + path_capability
            + "用户要「用浏览器打开 / 右坞打开 / 直播 / 帮我看页面」或已打开页短操作"
            "（搜一下 / 点一下 / 填一下）时："
            "必须你自己用对应 `browser_*` 完成"
            "（右坞会直播；**【禁止】**为此 `delegate`；「随便搜」省略过重验收），"
            "短操作或 navigate 成功即可收工（已打开即可，**【禁止】**口头假验收）；"
            "仅用户明确要「验收 / 截图 / 确认渲染」才 `delegate` 做 screenshot"
            "（screenshot 失败勿多轮空转补验）；"
            "「跑起来 / 打开看一下」≠必须 navigate。"
            "禁止编造 browser_open 等未列出的工具名；"
            "禁止只用 read_url / web_search 交差并假装已打开浏览器。"
            "仅当用户只要摘要/标题且未点名浏览器时，才可用 read_url。"
            "需要登录时 escalate(browser_login=true) 让用户在右坞「浏览器」接管登录"
            "（归还后点「已登录，继续」）；模型永不代填密码。"
            "勿声称已替用户打开系统浏览器。"
        )
    else:
        browser_base = (
            "浏览器指引：本回合 browser=未装配（无云端隔离浏览器 / 无本机 Bridge）——"
            "勿调用 browser_*、勿假装已打开或直播页面。"
        )
        intent_rule = (
            "用户要「用浏览器打开 / 右坞打开 / 直播 / 接管登录」时："
            "必须先如实说明未装配；"
            "可用 read_url / web_search 作文本摘录，但须标明「非右坞浏览器、未直播开页」，"
            "禁止静默用 read_url 交差让用户以为已打开浏览器。"
        )
        product_path = (
            "装配后的产品路径：CEO 直调 browser_navigate / snapshot / type / click "
            "打开或短操作目标页（「随便搜」省略过重验收；截图验收仍可 delegate）→"
            "需要登录则 escalate(browser_login=true) →"
            "用户在右坞「浏览器」接管 → 点「已登录，继续」；"
            "勿把「复制粘贴整页 / 扫本机 Cookie / 系统浏览器代登」说成主产品路径"
            "（用户主动贴文本可作补救，但不是接管流程）。"
        )
        if is_local:
            how_enable = (
                "要启用：本机会话需桌面 Local Chromium Bridge 健康，"
                "或启用云端沙箱浏览器；"
            )
        elif desktop_online:
            how_enable = (
                "要启用：桌面端优先 `bind_local_folder`（本机 Local+Bridge）"
                "或 `open_local_project`，或启用云端沙箱浏览器；"
            )
        else:
            how_enable = (
                "要启用：当前非桌面会话无法绑定本机 Local；"
                "可换桌面端或启用云端沙箱浏览器；"
            )
        browser_guide_line = browser_base + intent_rule + how_enable + product_path

    # Prefer explicit languages; else a probe cached on the backend.
    langs = exec_languages
    if langs is None:
        langs = getattr(backend, "_exec_languages", None)
    interpreters_line: str | None = None
    if exec_on and langs is not None:
        from agentcore.tools.sandbox.exec_languages import format_interpreters_line

        interpreters_line = format_interpreters_line(tuple(langs))

    # 案卷布局（始终可见）：三行出口 + 一句边界。只陈述路径事实，不注入文档正文进 <rules>。
    dossier_research_line = f"案卷出口·调研/讨论：`{RESEARCH_DIR}/`"
    dossier_debate_line = f"案卷出口·辩论副产物：`{DEBATE_DIR}/`"
    dossier_reviews_line = f"案卷出口·审查：`{REVIEWS_DIR}/`"
    dossier_boundary_line = (
        "案卷边界：讨论/调研/审查类交付写此树；用户工程源码仍写业务路径。"
    )
    # Git is optional: most cloud scratches / unbound trees have no `.git` at root.
    git_line = (
        "版本控制：通常无 Git（仅识别工作区根 `.git`，不扫嵌套、不上溯；"
        "只读 status/diff/log 无仓 → no_repo，写入仍硬错）。"
    )

    body_lines = [
        location_line,
        identity_line,
        reach_line,
        artifact_line,
        dossier_research_line,
        dossier_debate_line,
        dossier_reviews_line,
        dossier_boundary_line,
        git_line,
        desktop_line,
        grant_line,
        mounts_line,
        capability_line,
        host_guide_line,
        mcp_guide_line,
        browser_guide_line,
    ]
    if interpreters_line is not None:
        body_lines.append(interpreters_line)
    body = "\n".join(body_lines)
    return f"<workspace_context>\n{body}\n</workspace_context>"
