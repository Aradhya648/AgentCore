"""Shared workspace capacity ceilings (capacity contract ≠ liveness timeout).

Byte / entry ceilings fail fast as capacity contracts. Wall-clock timeouts are a
separate liveness signal (see ``runtime.engine.tool_deadline`` + tool_exec).

Aligned with desktop ``WORKSPACE_READ_MAX`` (``apps/desktop/src/main/fs/constants.ts``).
"""

from __future__ import annotations

# Whole-file read ceiling (text / bytes / line windows that load the file).
WORKSPACE_READ_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB — mirrors desktop Local

# Office/PDF transparent extract: tighter than raw read so markitdown cannot burn
# the liveness wall-clock on a multi-MiB PDF that still fits the read ceiling.
OFFICE_EXTRACT_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB

# Exact detail string shared with desktop ``opErr("WorkspaceIOError", …)``.
FILE_TOO_LARGE_DETAIL = "文件过大，无法读取"

# Channel / tool-result markers for hung desktop / cancelled transport (not capacity).
LIVENESS_TIMEOUT_DETAIL_MARKERS = (
    "timed out",
    "活性挂起",
)

# Local workspace IO family retired together when the desktop channel is sticky-dead
# (fail-fast alone still lets the model thrash / re-delegate writers).
WORKSPACE_CHANNEL_DEAD_RETIRE_TOOLS: tuple[str, ...] = (
    "file_read",
    "file_list",
    "file_write",
    "file_append",
    "str_replace",
    "write_section",
    "file_delete",
    "file_move",
    "file_copy",
    "file_batch",
    "mkdir",
    "grep",
    "host_ping",
)

WORKSPACE_CHANNEL_DEAD_RETIRE_STEER = (
    "本地工作区文件通道已挂起（活性无响应）：本回合起停用全部本地文件读写工具。"
    "请向用户说明「本地文件暂时连不上」，基于已有信息收口或请用户检查桌面连接后重试；"
    "禁止再调用文件工具，也禁止再派需要读写本地文件的队员。"
)


def is_file_too_large_detail(detail: str | None) -> bool:
    """True when a workspace I/O detail is the shared oversized-file capacity signal."""
    text = (detail or "").strip()
    return text == FILE_TOO_LARGE_DETAIL or text.startswith(FILE_TOO_LARGE_DETAIL)


def is_liveness_timeout_detail(detail: str | None) -> bool:
    """True when a workspace/channel failure is a hang / no-response timeout."""
    text = (detail or "").lower()
    return any(m.lower() in text for m in LIVENESS_TIMEOUT_DETAIL_MARKERS)


def channel_dead_retire_metadata() -> dict[str, object]:
    """ToolResult.metadata for sticky channel-dead (first-fail retire + steer)."""
    return {
        "liveness_timeout": True,
        "timeout_layer": "channel",
        "error_class": "permanent",
        "workspace_channel_dead": True,
        "retire_tools": list(WORKSPACE_CHANNEL_DEAD_RETIRE_TOOLS),
        "retire_message": WORKSPACE_CHANNEL_DEAD_RETIRE_STEER,
    }


def channel_dead_error_message(detail: str) -> str:
    """User/model-facing error text when the local file channel is sticky-dead."""
    return (
        f"本地工作区通道活性挂起（无响应）：{detail}。"
        "这不是文件过大或参数合同失败——"
        f"{WORKSPACE_CHANNEL_DEAD_RETIRE_STEER}"
    )
