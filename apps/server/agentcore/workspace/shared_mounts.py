"""Cloud second-root mounts for shared spaces (``shared/<alias>/…``).

Distinct from W3 ``external/`` grants (desktop roots, readonly/organize): shared
mounts point at server disk ``workspaces/shared/<space_id>/`` and map member
roles to real read/write. Realtime membership is re-checked at tool-call
granularity by the workspace backend gate — not cached for the whole turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SHARED_PREFIX = "shared/"
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_READONLY_MSG = "共享空间挂载为只读，不能写入"
_REVOKED_MSG = "共享空间挂载已失效（成员资格或角色已变更）"

SharedMountMode = Literal["readonly", "write"]


@dataclass(frozen=True)
class SharedMount:
    """One session-scoped shared-space mount under ``shared/<alias>/``."""

    alias: str
    space_id: str
    label: str
    mode: SharedMountMode


@dataclass(frozen=True)
class RoutedShared:
    mount: SharedMount
    rel: str


def sanitize_alias(raw: str) -> str:
    s = (raw or "").strip().replace("\\", "/").rstrip("/")
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    s = re.sub(r"[^\w.-]+", "_", s, flags=re.UNICODE).strip("._-")
    if not s:
        s = "space"
    if s[0].isdigit():
        s = f"s_{s}"
    return s[:64]


def uniquify_alias(base: str, taken: set[str]) -> str:
    alias = sanitize_alias(base)
    if alias not in taken:
        return alias
    n = 2
    while f"{alias}_{n}" in taken:
        n += 1
    return f"{alias}_{n}"


def parse_shared_path(path: str) -> tuple[str, str] | None:
    """If ``path`` is under ``shared/<alias>/…``, return ``(alias, rel)``."""
    raw = (path or "").strip().replace("\\", "/").lstrip("/")
    if not raw.startswith(SHARED_PREFIX):
        return None
    rest = raw[len(SHARED_PREFIX) :]
    if not rest:
        return None
    alias, _, rel = rest.partition("/")
    if not alias or not _ALIAS_RE.match(alias):
        return None
    return alias, rel


def route_shared(path: str, mounts: dict[str, SharedMount]) -> RoutedShared | None:
    parsed = parse_shared_path(path)
    if parsed is None:
        return None
    alias, rel = parsed
    mount = mounts.get(alias)
    if mount is None:
        return None
    return RoutedShared(mount=mount, rel=rel)


def shared_ns(alias: str, rel: str = "") -> str:
    rel = (rel or "").replace("\\", "/").strip("/")
    return f"{SHARED_PREFIX}{alias}/{rel}" if rel else f"{SHARED_PREFIX}{alias}"


def readonly_write_error(path: str) -> str:
    return f"{_READONLY_MSG}（拒绝写入 `{path}`）"


def revoked_error(path: str = "") -> str:
    if path:
        return f"{_REVOKED_MSG}（拒绝 `{path}`）"
    return _REVOKED_MSG
