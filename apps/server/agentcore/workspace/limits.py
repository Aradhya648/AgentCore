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


def is_file_too_large_detail(detail: str | None) -> bool:
    """True when a workspace I/O detail is the shared oversized-file capacity signal."""
    text = (detail or "").strip()
    return text == FILE_TOO_LARGE_DETAIL or text.startswith(FILE_TOO_LARGE_DETAIL)


def is_liveness_timeout_detail(detail: str | None) -> bool:
    """True when a workspace/channel failure is a hang / no-response timeout."""
    text = (detail or "").lower()
    return any(m.lower() in text for m in LIVENESS_TIMEOUT_DETAIL_MARKERS)
