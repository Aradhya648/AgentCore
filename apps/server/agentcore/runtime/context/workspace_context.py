"""Per-turn ``<workspace_context>`` — structured environment facts for CEO and workers.

根治「模型环境盲」：每回合把执行位置、工作区身份、桌面通道、本回合可执行能力写成显式
事实块注入 system prompt，避免 CEO 在云端 scratch 上规划「打开本机软件」并空跑委派。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from agentcore.workspace.stage_dirs import DEBATE_DIR, RESEARCH_DIR, REVIEWS_DIR

if TYPE_CHECKING:
    from agentcore.workspace.protocol import WorkspaceBackend


def desktop_client_can_bind(x_client_platform: str | None) -> bool:
    """Whether the calling client can fulfil ``AskOption.action=bind_local_folder``.

    Only the Electron desktop app renders the folder-picker action. Mobile sends
    ``mobile-web`` / ``mobile``; admin is unrelated. Absent header defaults to desktop
    (legacy tests / curl — same posture as ``parse_client_platform``).
    """
    raw = (x_client_platform or "desktop").strip().lower()
    return raw == "desktop"


def build_workspace_context(
    backend: WorkspaceBackend | None,
    *,
    desktop_online: bool,
    code_execute_enabled: bool | None = None,
    terminal_enabled: bool | None = None,
    browser_enabled: bool | None = None,
    exec_languages: list[str] | tuple[str, ...] | None = None,
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
            "用户可在「文件」面板查看 / 预览，或直接在本机打开。"
        )
    else:
        location_line = "执行位置：云端沙箱（服务端）"
        # 裸聊默认云 scratch：空树 ≠ 本机/已打开仓库。对模型显式纠偏，避免把宿主路径当项目。
        identity_line = (
            f"工作区身份：本会话云端草稿/临时文件空间（根标签 `{root_label}`）——"
            "不是用户本机目录，也不是用户本机已打开的仓库或项目工作区。"
        )
        reach_line = (
            "云端沙箱触达不了用户的电脑、本机应用与本机文件；"
            "不要假设能打开或安装用户机器上的软件；"
            "空树只表示本会话云端草稿尚无文件，勿当成「本机空项目」或宿主机器上的 Git 仓库。"
        )
        artifact_line = (
            "产物出口：你写入工作区的文件保存在云端工作区（不在用户本机），"
            "用户可在桌面端「文件」面板直接查看、预览与下载；"
            "不要让用户去本机磁盘或本地路径查找这些文件，"
            "也不要声称文件已在用户电脑上、或让其在本地「双击打开」。"
        )

    if desktop_online:
        if is_local:
            desktop_line = "客户端通道：桌面端在线（本机执行通道可用）。"
            grant_line = (
                "区外目录：可用 ask_user 选项 `action=grant_readonly_folder` 请求"
                "会话级只读授权；确认后以 `external/<别名>/…` 访问（只读、仅本次对话、可撤销）。"
            )
        else:
            desktop_line = (
                "客户端通道：桌面端在线——需本机能力时【立即】发 ask_user 卡，"
                "选项标 `action=bind_local_folder`（勿用纯文本解释或询问）；"
                "绑定完成前不要委派本机任务。"
                "已建云端会话的本机出路=本会话发绑定卡（执行环境绑定）；"
                "「在哪工作」仅新建会话可选（快速对话=云端默认 / 本机草稿 / 项目），"
                "勿引导用户去设置改模式。"
            )
            grant_line = (
                "区外目录授权需先处在本地工作区；当前为云端时先发绑定卡，"
                "或如实说明云端无法直接授权本机区外路径。"
            )
    else:
        desktop_line = (
            "客户端通道：桌面端不在线（当前为 Web / 移动端等非桌面会话）——"
            "无法发起本机文件夹绑定；需要本机能力时如实说明限制。"
        )
        grant_line = "区外目录只读授权仅桌面本地会话可用；当前客户端无法履行。"

    mounts = getattr(backend, "_mounts", None) or {}
    if mounts:
        parts = [
            f"`external/{a}/`（{getattr(m, 'label', a)}，只读）"
            for a, m in mounts.items()
        ]
        mounts_line = "本对话已授权区外目录：" + "；".join(parts) + "。"
    else:
        mounts_line = "本对话尚无会话级区外目录授权。"

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
    caps: list[str] = []
    caps.append(f"code_execute={'已装配' if exec_on else '未装配'}")
    caps.append(f"terminal={'已装配' if term_on else '未装配'}")
    caps.append(f"browser={'已装配' if browser_on else '未装配'}")
    caps.append(f"local_open={'已装配' if local_open_on else '未装配'}")
    capability_line = "本回合执行能力：" + "；".join(caps) + "。"

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

    body_lines = [
        location_line,
        identity_line,
        reach_line,
        artifact_line,
        dossier_research_line,
        dossier_debate_line,
        dossier_reviews_line,
        dossier_boundary_line,
        desktop_line,
        grant_line,
        mounts_line,
        capability_line,
    ]
    if interpreters_line is not None:
        body_lines.append(interpreters_line)
    body = "\n".join(body_lines)
    return f"<workspace_context>\n{body}\n</workspace_context>"
