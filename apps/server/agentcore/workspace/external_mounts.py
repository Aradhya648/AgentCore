"""Session-level external directory mounts (W3 readonly + organize).

Model-facing paths use the relative namespace ``external/<alias>/…`` — absolute
OS paths never enter prompts. File tools route through these mounts; access is
gated by per-alias ``mode`` (readonly | organize). ``resolve_safe_path`` /
pathGuard algorithms are unchanged: each mount is a separate root passed into
the same guard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

EXTERNAL_PREFIX = "external/"
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_READONLY_MSG = "会话授权目录为只读，不能写入；请把产出写到对话工作区"
_ORGANIZE_DENY_MSG = (
    "整理授权不允许此操作（仅 list/read/grep/stat + move/copy/mkdir + 回收站删除）"
)
_PERMANENT_EXTERNAL_MSG = "区外目录禁止永久删除；请使用可逆删除（进回收站）"

ExternalMountMode = Literal["readonly", "organize"]

# Desktop / engine op names allowed under organize mode (read + organize mutations).
ORGANIZE_ALLOWED_OPS: frozenset[str] = frozenset(
    {
        # read
        "read",
        "read_bytes",
        "read_lines",
        "list",
        "list_tree",
        "index_files",
        "grep",
        "process_read",
        "process_list",
        "process_stop",
        # organize mutations
        "move",
        "copy",
        "mkdir",
        "delete",
    }
)

# Mutating ops organize may perform (workspace-layer semantic names).
ORGANIZE_MUTATION_OPS: frozenset[str] = frozenset({"move", "copy", "mkdir", "delete"})

# Explicit denials under organize (defense in depth; also absent from ALLOWED).
ORGANIZE_DENIED_OPS: frozenset[str] = frozenset(
    {
        "write",
        "append",
        "write_bytes",
        "replace",
        "execute",
        "process_start",
        "archive",
    }
)


@dataclass(frozen=True)
class ExternalMount:
    """One session-scoped directory grant under ``external/<alias>/``.

    ``root_id`` is the desktop authorized-root handle (LocalWorkspace channel).
    ``abs_path`` is set only where the engine has direct Path I/O (sidecar);
    cloud LocalWorkspace leaves it ``None`` and lets the desktop resolve.
    ``mode`` is explicit: never flip a bare ``readonly=False`` (that would also
    open execute / process_start / archive on the desktop dispatch path).
    """

    alias: str
    root_id: str
    label: str
    abs_path: str | None = None
    mode: ExternalMountMode = "readonly"

    @property
    def readonly(self) -> bool:
        """True when this mount is read-only (W3). Prefer ``mode`` for new code."""
        return self.mode == "readonly"


@dataclass(frozen=True)
class RoutedExternal:
    mount: ExternalMount
    """Path relative to the mount root (``""`` / ``"."`` = mount root itself)."""
    rel: str


def sanitize_alias(raw: str) -> str:
    """Derive a stable alias from a folder display name."""
    s = (raw or "").strip().replace("\\", "/").rstrip("/")
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    s = re.sub(r"[^\w.-]+", "_", s, flags=re.UNICODE).strip("._-")
    if not s:
        s = "folder"
    if s[0].isdigit():
        s = f"d_{s}"
    return s[:64]


def uniquify_alias(base: str, taken: set[str]) -> str:
    """Ensure ``base`` is unique within ``taken`` (append ``_2``, ``_3``, …)."""
    alias = sanitize_alias(base)
    if alias not in taken:
        return alias
    n = 2
    while f"{alias}_{n}" in taken:
        n += 1
    return f"{alias}_{n}"


def parse_external_path(path: str) -> tuple[str, str] | None:
    """If ``path`` is under ``external/<alias>/…``, return ``(alias, rel)``.

    ``rel`` is ``""`` when the path names the mount root itself.
    """
    raw = (path or "").strip().replace("\\", "/").lstrip("/")
    if not raw.startswith(EXTERNAL_PREFIX):
        return None
    rest = raw[len(EXTERNAL_PREFIX) :]
    if not rest:
        return None
    alias, _, rel = rest.partition("/")
    if not alias or not _ALIAS_RE.match(alias):
        return None
    return alias, rel


def route_external(
    path: str, mounts: dict[str, ExternalMount]
) -> RoutedExternal | None:
    """Route an ``external/<alias>/…`` path, or ``None`` when not external."""
    parsed = parse_external_path(path)
    if parsed is None:
        return None
    alias, rel = parsed
    mount = mounts.get(alias)
    if mount is None:
        return None
    return RoutedExternal(mount=mount, rel=rel)


def external_ns(alias: str, rel: str = "") -> str:
    """Build the model-facing path ``external/<alias>[/rel]``."""
    rel = (rel or "").replace("\\", "/").strip("/")
    return f"{EXTERNAL_PREFIX}{alias}/{rel}" if rel else f"{EXTERNAL_PREFIX}{alias}"


def readonly_write_error(path: str) -> str:
    return f"{_READONLY_MSG}（拒绝写入 `{path}`）"


def organize_deny_error(path: str, op: str) -> str:
    return f"{_ORGANIZE_DENY_MSG}（拒绝 `{op}` → `{path}`）"


def permanent_external_error(path: str) -> str:
    return f"{_PERMANENT_EXTERNAL_MSG}（拒绝 `{path}`）"


def normalize_mount_mode(raw: str | None) -> ExternalMountMode:
    text = (raw or "readonly").strip().lower()
    if text == "organize":
        return "organize"
    return "readonly"


def external_mutation_allowed(
    mount: ExternalMount,
    op: str,
    *,
    path: str = "",
    permanent: bool = False,
) -> str | None:
    """Return an error message when a mutating op is denied on this mount; else None.

    Routing-layer rules:
    - readonly → all mutations denied
    - permanent delete on any external mount → always denied (stricter than workspace)
    - organize → only move / copy / mkdir / non-permanent delete
    """
    label = path or external_ns(mount.alias)
    if permanent:
        return permanent_external_error(label)
    if mount.mode == "readonly":
        return readonly_write_error(label)
    if op in ORGANIZE_DENIED_OPS or op not in ORGANIZE_MUTATION_OPS:
        return organize_deny_error(label, op)
    return None


def desktop_op_allowed(
    mode: ExternalMountMode,
    op: str,
    *,
    permanent: bool = False,
) -> str | None:
    """Desktop dispatch gate: mode + op whitelist. None = allow."""
    if mode == "readonly":
        if op in ORGANIZE_ALLOWED_OPS and op not in ORGANIZE_MUTATION_OPS:
            return None
        # read-side process_stop etc. already in ALLOWED; anything else → readonly msg
        if op in ORGANIZE_MUTATION_OPS or op in ORGANIZE_DENIED_OPS:
            return _READONLY_MSG
        if op not in ORGANIZE_ALLOWED_OPS:
            return _READONLY_MSG
        return None
    # organize
    if permanent and op == "delete":
        return _PERMANENT_EXTERNAL_MSG
    if op in ORGANIZE_DENIED_OPS:
        return _ORGANIZE_DENY_MSG
    if op not in ORGANIZE_ALLOWED_OPS:
        return _ORGANIZE_DENY_MSG
    return None


def external_env_var(alias: str) -> str:
    """Env var name for code_execute injection (absolute path value)."""
    safe = re.sub(r"[^A-Za-z0-9]+", "_", alias).strip("_").upper() or "FOLDER"
    return f"AGENTCORE_EXTERNAL_{safe}"


def build_external_env(mounts: dict[str, ExternalMount]) -> dict[str, str]:
    """Map alias → abs path for code_execute env injection.

    Organize mounts are **excluded** (proposal §五): file tools are the only
    supported external write path under organize. Skips missing abs.
    """
    out: dict[str, str] = {}
    for alias, m in mounts.items():
        if m.mode == "organize":
            continue
        if m.abs_path:
            out[external_env_var(alias)] = m.abs_path
    return out
