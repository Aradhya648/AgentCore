"""Background-process tool — spawn / read / stop / list long-lived commands.

Worker-only, local-mode only (``backend.location == "local"``). Processes are held
by the desktop main process; this tool routes four ``WorkspaceOp`` values over the
existing ``workspace_op_required`` channel (云 LocalWorkspace 与 sidecar 同路).

Schema stays ``ToolApproval.NEVER`` so read / stop / list skip the gate; ``start``
is gated via ``tool_call_requires_approval`` (same posture as ``git`` write
subcommands). See docs/03-AI核心/工具与能力系统.md (terminal 行).
"""

from __future__ import annotations

import time
from typing import Any

from agentcore.config import settings
from agentcore.core.types import ToolApproval, ToolCategory
from agentcore.tools.builtin.long_running import (
    long_running_command_match,
    readiness_footer,
    wait_for_required_message,
)
from agentcore.tools.protocol import ToolContext, ToolResult, ToolSchema
from agentcore.tools.registration import (
    AUDIENCE_WORKER_ONLY,
    ToolRegistration,
    ToolSurface,
)
from agentcore.workspace.channel import WorkspaceOp
from agentcore.workspace.protocol import WorkspaceError

_ALLOWED_SUBCOMMANDS = frozenset({"start", "read", "stop", "list"})
_APPROVAL_SUBCOMMANDS = frozenset({"start"})

# Spawn / first-chunk ceiling when ``wait_for`` is absent (channel + engine).
_FAST_TIMEOUT_SECONDS = 60.0
_DEFAULT_WAIT_TIMEOUT_SECONDS = 30.0
_MAX_WAIT_TIMEOUT_SECONDS = 300.0

TERMINAL_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subcommand": {
            "type": "string",
            "enum": ["start", "read", "stop", "list"],
            "description": (
                "start：启动长时进程并返回 process_id + 首段输出；"
                "read：读尾部输出 / 按 regex 等待新输出；"
                "stop：终止进程；"
                "list：列出本对话进程（可能含用户交互终端「用户终端 #N」，可读不可停）。"
            ),
        },
        "command": {
            "type": "string",
            "description": "start 时要启动的命令（shell 字符串，如 `pnpm dev`）。",
        },
        "cwd": {
            "type": "string",
            "description": "start 的工作目录（工作区相对路径，可选；默认工作区根）。",
        },
        "wait_for": {
            "type": "string",
            "description": (
                "start / read：等待输出匹配此正则后再返回"
                "（如 Local:|ready in|Listening）。"
                "启动 npm run dev / vite / next dev 等长驻进程时【必填】。"
            ),
        },
        "wait_timeout_seconds": {
            "type": "number",
            "description": (
                f"wait_for 最长等待秒数（默认 {_DEFAULT_WAIT_TIMEOUT_SECONDS:.0f}，"
                f"上限 {_MAX_WAIT_TIMEOUT_SECONDS:.0f}）。"
            ),
            "default": _DEFAULT_WAIT_TIMEOUT_SECONDS,
        },
        "name": {
            "type": "string",
            "description": "start 可选：进程显示名（终端 tab 用）。",
        },
        "process_id": {
            "type": "string",
            "description": "read / stop 的进程 id（start 返回值）。",
        },
        "tail_lines": {
            "type": "integer",
            "description": "read 可选：返回末尾最多 N 行（默认由桌面侧决定）。",
        },
        "purpose": {
            "type": "string",
            "description": (
                "一句话中文说明为何启动该进程；会展示给用户作为审批说明，执行时忽略"
            ),
        },
    },
    "required": ["subcommand"],
}


def terminal_approval_subcommands() -> frozenset[str]:
    """Subcommands that require user approval (``start`` only)."""
    return _APPROVAL_SUBCOMMANDS


def clamp_wait_timeout_seconds(raw: Any) -> float:
    """Normalize ``wait_timeout_seconds`` into ``[1, MAX]`` (default when missing)."""
    if raw is None:
        return _DEFAULT_WAIT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_WAIT_TIMEOUT_SECONDS
    return max(1.0, min(value, _MAX_WAIT_TIMEOUT_SECONDS))


def terminal_op_timeout_seconds(arguments: dict[str, Any] | None) -> float:
    """Per-op channel / engine ceiling for one ``terminal`` call.

    With ``wait_for``, both the channel transport deadline and
    ``resolve_tool_timeout`` must outlive ``wait_timeout + slack`` so the tool
    layer does not cancel while the desktop is still waiting for the ready signal.
    Without ``wait_for``, start returns after spawn + first chunk (fast path).
    """
    slack = float(settings.workspace_execute_timeout_slack_seconds)
    if not arguments:
        return _FAST_TIMEOUT_SECONDS
    wait_for = str(arguments.get("wait_for") or "").strip()
    if not wait_for:
        return _FAST_TIMEOUT_SECONDS
    return clamp_wait_timeout_seconds(arguments.get("wait_timeout_seconds")) + slack


def _error(error: str, start: float) -> ToolResult:
    return ToolResult(
        tool_call_id="",
        success=False,
        output="",
        error=error,
        duration_ms=int((time.monotonic() - start) * 1000),
    )


def _format_process_output(
    value: dict[str, Any], *, had_wait_for: bool = False
) -> str:
    process_id = value.get("process_id", "")
    status = str(value.get("status", ""))
    output = str(value.get("output") or "")
    matched = value.get("matched")
    exit_code = value.get("exit_code")
    lines = [f"process_id: {process_id}", f"status: {status}"]
    if matched is not None:
        lines.append(f"matched: {matched}")
    if exit_code is not None:
        lines.append(f"exit_code: {exit_code}")
    if output:
        lines.append(f"output:\n{output}")
    else:
        lines.append("output:（无）")
    body = "\n".join(lines)
    matched_flag: bool | None
    if matched is True:
        matched_flag = True
    elif matched is False:
        matched_flag = False
    else:
        matched_flag = None
    return body + readiness_footer(
        status=status,
        matched=matched_flag,
        had_wait_for=had_wait_for,
        exit_code=exit_code,
    )


def _format_list_output(processes: list[Any]) -> str:
    if not processes:
        return "（本对话无后台进程）"
    lines: list[str] = []
    for item in processes:
        if not isinstance(item, dict):
            continue
        pid = item.get("process_id", "")
        status = item.get("status", "")
        command = item.get("command", "")
        name = item.get("name")
        started = item.get("started_at", "")
        exit_code = item.get("exit_code")
        label = f"{name} " if name else ""
        line = f"- {label}id={pid} status={status} command={command}"
        if started:
            line += f" started_at={started}"
        if exit_code is not None:
            line += f" exit_code={exit_code}"
        lines.append(line)
    return "\n".join(lines) if lines else "（本对话无后台进程）"


def _process_display(subcommand: str, value: dict[str, Any]) -> dict[str, Any]:
    display: dict[str, Any] = {"subcommand": subcommand}
    for key in ("process_id", "status", "output", "matched", "exit_code", "command", "name"):
        if key in value:
            display[key] = value[key]
    if "processes" in value:
        display["processes"] = value["processes"]
    return display


class TerminalTool:
    """Spawn and manage long-lived processes on the user's desktop."""

    registration = ToolRegistration(
        surface=ToolSurface.WORKER_ONLY,
        audience=AUDIENCE_WORKER_ONLY,
        execution_class=True,
        local_only=True,
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="terminal",
            description=(
                "在用户本机启动/管理长时后台进程（dev server、watch、长脚本等）。"
                "【凡永不退出的命令必须用本工具，禁止改走 code_execute】"
                "典型：npm run dev / vite / next dev / uvicorn --reload。"
                "start：spawn 并返回 process_id + 首段输出；宣称「已就绪」前应用 "
                "wait_for（如 Local:|ready in）等到 ready 信号，勿仅凭首段输出下结论；"
                "read：读尾部输出或按正则等待；stop：终止；list：列本对话进程"
                "（可能含用户交互终端「用户终端 #N」，可读不可停）。"
                "会自行退出的短命令（npm install、build、test）请用 code_execute。"
                "仅本地模式可用，进程跨回合存活。"
            ),
            parameters=TERMINAL_TOOL_PARAMETERS,
            category=ToolCategory.EXECUTION,
            approval=ToolApproval.NEVER,
            # Dynamic ceiling via resolve_tool_timeout(arguments=…); schema leaves
            # None so the category default is not a hard 90s cap under wait_for.
            timeout_seconds=None,
        )

    async def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        start = time.monotonic()
        channel = context.workspace_channel
        if channel is None:
            return _error(
                "terminal 仅在本地工作区可用：当前无桌面进程通道，无法托管后台进程。"
                "需本机终端时：桌面在线则立即发 ask_user 卡（action=bind_local_folder），"
                "勿用纯文本询问。",
                start,
            )

        subcommand = str(arguments.get("subcommand", "")).strip().lower()
        if not subcommand:
            return _error("subcommand 为必填参数", start)
        if subcommand not in _ALLOWED_SUBCOMMANDS:
            return _error(f"子命令 '{subcommand}' 不在允许列表中", start)

        try:
            if subcommand == "start":
                return await self._cmd_start(arguments, context, start)
            if subcommand == "read":
                return await self._cmd_read(arguments, context, start)
            if subcommand == "stop":
                return await self._cmd_stop(arguments, context, start)
            return await self._cmd_list(context, start)
        except WorkspaceError as e:
            return _error(str(e) or e.__class__.__name__, start)

    async def _cmd_start(
        self, arguments: dict[str, Any], context: ToolContext, start: float
    ) -> ToolResult:
        command = str(arguments.get("command") or "").strip()
        if not command:
            return _error("start 需要 command 参数", start)

        wait_for = str(arguments.get("wait_for") or "").strip()
        # 就绪验收闸：长驻 CLI 无 wait_for → 拒启动，逼模型带 ready 信号。
        if not wait_for:
            detected = long_running_command_match(command)
            if detected is not None:
                return ToolResult(
                    tool_call_id="",
                    success=False,
                    output="",
                    error=wait_for_required_message(detected),
                    duration_ms=int((time.monotonic() - start) * 1000),
                    metadata={"code": "wait_for_required", "matched": detected},
                    contract_failure=True,
                )

        args: dict[str, Any] = {"command": command}
        cwd = str(arguments.get("cwd") or "").strip()
        if cwd:
            args["cwd"] = cwd
        if wait_for:
            args["wait_for"] = wait_for
            args["wait_timeout_seconds"] = clamp_wait_timeout_seconds(
                arguments.get("wait_timeout_seconds")
            )
        name = str(arguments.get("name") or "").strip()
        if name:
            args["name"] = name

        assert context.workspace_channel is not None
        value = await context.workspace_channel.request(
            WorkspaceOp.PROCESS_START,
            args,
            timeout=terminal_op_timeout_seconds(arguments),
        )
        return self._process_result("start", value, start, had_wait_for=bool(wait_for))

    async def _cmd_read(
        self, arguments: dict[str, Any], context: ToolContext, start: float
    ) -> ToolResult:
        process_id = str(arguments.get("process_id") or "").strip()
        if not process_id:
            return _error("read 需要 process_id 参数", start)

        args: dict[str, Any] = {"process_id": process_id}
        wait_for = str(arguments.get("wait_for") or "").strip()
        if wait_for:
            args["wait_for"] = wait_for
            args["wait_timeout_seconds"] = clamp_wait_timeout_seconds(
                arguments.get("wait_timeout_seconds")
            )
        if arguments.get("tail_lines") is not None:
            try:
                args["tail_lines"] = int(arguments["tail_lines"])
            except (TypeError, ValueError):
                return _error("tail_lines 必须是整数", start)

        assert context.workspace_channel is not None
        value = await context.workspace_channel.request(
            WorkspaceOp.PROCESS_READ,
            args,
            timeout=terminal_op_timeout_seconds(arguments),
        )
        return self._process_result("read", value, start, had_wait_for=bool(wait_for))

    async def _cmd_stop(
        self, arguments: dict[str, Any], context: ToolContext, start: float
    ) -> ToolResult:
        process_id = str(arguments.get("process_id") or "").strip()
        if not process_id:
            return _error("stop 需要 process_id 参数", start)

        assert context.workspace_channel is not None
        value = await context.workspace_channel.request(
            WorkspaceOp.PROCESS_STOP,
            {"process_id": process_id},
        )
        return self._process_result("stop", value, start, had_wait_for=False)

    async def _cmd_list(self, context: ToolContext, start: float) -> ToolResult:
        assert context.workspace_channel is not None
        value = await context.workspace_channel.request(WorkspaceOp.PROCESS_LIST, {})
        if not isinstance(value, dict):
            return _error("桌面返回了无效的 process_list 结果", start)
        processes = value.get("processes") or []
        if not isinstance(processes, list):
            processes = []
        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=_format_list_output(processes),
            duration_ms=duration_ms,
            display=_process_display("list", {"processes": processes}),
        )

    def _process_result(
        self,
        subcommand: str,
        value: Any,
        start: float,
        *,
        had_wait_for: bool,
    ) -> ToolResult:
        if not isinstance(value, dict) or not value.get("process_id"):
            return _error(f"桌面返回了无效的 {subcommand} 结果", start)
        duration_ms = int((time.monotonic() - start) * 1000)
        # stop：目标就是退出，不加「就绪判定」脚注。
        if subcommand == "stop":
            process_id = value.get("process_id", "")
            status = value.get("status", "")
            exit_code = value.get("exit_code")
            lines = [f"process_id: {process_id}", f"status: {status}"]
            if exit_code is not None:
                lines.append(f"exit_code: {exit_code}")
            output = "\n".join(lines)
        else:
            output = _format_process_output(value, had_wait_for=had_wait_for)
        return ToolResult(
            tool_call_id="",
            success=True,
            output=output,
            duration_ms=duration_ms,
            display=_process_display(subcommand, value),
        )
