"""Product-landing path gate for ``form=files`` / ``requires_files``.

Any successful workspace write counts as product landing — including intermediate
dossier notes under ``AgentCore/文档/{research,reviews,debate}/``. Declared
``deliverable.artifacts`` no longer gate whether a dossier path counts.
"""

from __future__ import annotations

from collections.abc import Sequence

from agentcore.runtime.runs.contract import _normalize_artifact_relpath
from agentcore.workspace._paths import sanitize_write_relpath
from agentcore.workspace.stage_dirs import (
    DEBATE_DIR,
    DEBATE_PREFIX,
    RESEARCH_DIR,
    RESEARCH_PREFIX,
    REVIEWS_DIR,
    REVIEWS_PREFIX,
)

__all__ = [
    "is_dossier_intermediate_path",
    "is_product_landing_path",
    "filter_product_landing_paths",
    "landing_tool_path_from_args",
]


def is_dossier_intermediate_path(path: str) -> bool:
    """True when ``path`` sits under research / reviews / debate stage dirs."""
    p = _normalize_artifact_relpath(path)
    if not p:
        return False
    return (
        p in (RESEARCH_DIR, REVIEWS_DIR, DEBATE_DIR)
        or p.startswith(RESEARCH_PREFIX)
        or p.startswith(REVIEWS_PREFIX)
        or p.startswith(DEBATE_PREFIX)
    )


def is_product_landing_path(
    path: str | None,
    artifacts: Sequence[str] | None = None,
) -> bool:
    """Whether a landed path counts as product for files-form gates.

    Every workspace write counts (dossier notes included). Missing / empty path
    → ``True`` (compat for ``ToolAttempt`` without ``meta.path``). ``artifacts``
    is retained for call-site compatibility and is not consulted.
    """
    _ = artifacts
    return True


def filter_product_landing_paths(
    paths: Sequence[str],
    artifacts: Sequence[str] | None = None,
) -> list[str]:
    """Keep non-empty landed paths (stable order). ``artifacts`` unused (compat)."""
    _ = artifacts
    out: list[str] = []
    for raw in paths:
        if not raw or not str(raw).strip():
            continue
        out.append(str(raw))
    return out


def landing_tool_path_from_args(tool_name: str, args: dict | None) -> str | None:
    """Extract workspace path from landing-tool args (``file_move`` → destination).

    Applies :func:`sanitize_write_relpath` so harvested paths match what write
    tools actually land on disk.
    """
    if not isinstance(args, dict):
        return None
    key = "destination" if tool_name == "file_move" else "path"
    if tool_name not in {
        "file_write",
        "file_append",
        "str_replace",
        "write_section",
        "file_move",
    }:
        return None
    raw = args.get(key)
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().replace("\\", "/")
    if not cleaned:
        return None
    return sanitize_write_relpath(cleaned)
