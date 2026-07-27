"""LocalWorkspace — files and code execution on the user's machine (local mode).

The second ``WorkspaceBackend`` implementation. It owns no disk of its own: every
op is serialized and routed over a ``WorkspaceChannel`` to the bound desktop
client, which runs it against the real local directory (reusing the desktop's
authorized FS roots + traversal guard) and posts back a structured result. The
backend then returns the same typed values / raises the same ``WorkspaceError``
subclasses as ``ServerWorkspace`` — so the file tools and the engine run against
it **unchanged** (the whole point of the P0 seam).

All ops (read / list / grep / ``code_search`` / the mutating ops / ``execute``) are
wired end-to-end through the channel and handled by the desktop — except the BM25
index SQLite file, which lives under the API ``data_dir/code_index/`` (channel cannot
open a desktop SQLite handle). Sidecar local turns use ``ServerWorkspace`` on disk
instead and keep the index beside the workspace. Two policies make ``execute`` safe
on the user's real machine (双模式工作区 P2d 执行门):

* **Approval** is enforced *upstream* at the engine's ``ApprovalGate`` (before the
  op is ever issued), for the CEO and — in local mode — for delegated workers too,
  so no code runs on the user's machine without consent. The channel itself adds
  no gate (that would double-prompt the CEO).
* **Timeout**: ``execute`` extends the channel's transport deadline to the code's
  own ``timeout_seconds`` plus a slack, so the desktop's execution limit stays
  authoritative and a long but legal run is not cut off by the flat file-op
  deadline. A dropped desktop still fails as a ``WorkspaceIOError`` (never hangs).
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any

from agentcore.config import settings
from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult
from agentcore.workspace._paths import normalize_workspace_path
from agentcore.workspace.channel import WorkspaceChannel, WorkspaceOp
from agentcore.workspace.external_mounts import (
    ExternalMount,
    external_mutation_allowed,
    external_ns,
    parse_external_path,
    route_external,
)
from agentcore.workspace.indexing.manager import IndexManager
from agentcore.workspace.protocol import (
    CodeSearchResult,
    DirEntry,
    GrepHit,
    GrepQuery,
    GrepResult,
    OutsideWorkspace,
    PathNotFound,
    ReadLinesResult,
    ReplaceOutcome,
    TreeEntry,
    TreeResult,
)

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")

# Default extra transport budget (seconds) over a code execution's own timeout
# (see Settings.workspace_execute_timeout_slack_seconds). Used when a LocalWorkspace
# is built without an explicit slack (e.g. tests); locate.py injects the configured
# value for real turns.
_DEFAULT_EXECUTE_TIMEOUT_SLACK = 30.0


class LocalWorkspace:
    """``WorkspaceBackend`` backed by the desktop, reached over a channel."""

    location = "local"

    def __init__(
        self,
        channel: WorkspaceChannel,
        *,
        root_label: str = "workspace",
        execute_timeout_slack: float = _DEFAULT_EXECUTE_TIMEOUT_SLACK,
        base_subpath: str = "",
    ) -> None:
        self._channel = channel
        self.root_label = root_label
        # Added to an execute's own timeout to form its transport deadline, so the
        # desktop's execution limit (not the channel) decides when code is killed.
        self._execute_timeout_slack = execute_timeout_slack
        # Sub-directory within the bound root this workspace is scoped to (工作区
        # 对称化 D1a). Empty = the root itself (current behavior, every op below is a
        # no-op pass-through). Non-empty = every op path is prefixed with it on the
        # way to the desktop and stripped on the way back, so the engine, tools, and
        # the user only ever see workspace-relative paths — the container root the
        # channel is bound to never leaks. POSIX, no trailing slash.
        self._base = base_subpath.strip("/")
        # Flips True on the first mutating op so the service snapshots only
        # workspaces a turn actually changed (see WorkspaceBackend.dirty). For
        # local mode the snapshot is the 本地→云 handoff bridge (§四 / P2e).
        self._dirty = False
        # W3 session read-only mounts (``external/<alias>/…``). Empty by default;
        # ``attach_external_mounts`` wires grants at turn start.
        self._mounts: dict[str, ExternalMount] = {}
        # BM25 index lives on the API host (channel cannot open SQLite on the
        # desktop). Keyed by desktop root + subpath so fallback cloud→desktop
        # turns share one cache. Sidecar local turns use ServerWorkspace instead.
        self._index_manager: IndexManager | None = None

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _get_index_manager(self) -> IndexManager:
        if self._index_manager is None:
            self._index_manager = IndexManager(str(self._index_cache_dir()))
        return self._index_manager

    def _index_cache_dir(self) -> Path:
        root_key = _SAFE_SEGMENT.sub("_", self._channel.root_id or "unknown")[:80]
        base_digest = hashlib.sha256(self._base.encode("utf-8")).hexdigest()[:16]
        return Path(settings.data_dir) / "code_index" / root_key / base_digest

    def attach_external_mounts(self, mounts: dict[str, ExternalMount]) -> None:
        """Attach session-scoped read-only mounts for this turn (W3)."""
        self._mounts = dict(mounts)

    def _route(
        self,
        path: str,
        *,
        write: bool = False,
        op: str | None = None,
        permanent: bool = False,
    ) -> tuple[str | None, str, str | None]:
        """Map a model path to ``(override_root_id, desktop_rel, alias)``.

        ``override_root_id is None`` → primary workspace binding (apply ``_in``).
        Unknown ``external/<alias>`` → ``PathNotFound``. Mutations gated by mount
        ``mode`` (readonly vs organize whitelist; permanent delete always denied).
        """
        parsed = parse_external_path(path)
        if parsed is None:
            # Same contract as ServerWorkspace.resolve_safe_path / desktop pathGuard:
            # bare `/`/`\` → `.`; `/<root_label>/…` strip — before the channel sees it.
            norm = normalize_workspace_path(path, root_label=self.root_label)
            return None, self._in(norm), None
        routed = route_external(path, self._mounts)
        if routed is None:
            raise PathNotFound(path)
        if write:
            err = external_mutation_allowed(
                routed.mount,
                op or "write",
                path=path,
                permanent=permanent,
            )
            if err:
                raise OutsideWorkspace(err)
        rel = routed.rel if routed.rel not in ("", ".") else "."
        return routed.mount.root_id, rel, routed.mount.alias

    def _out_routed(self, path: str, alias: str | None) -> str:
        if alias is None:
            return self._out(path)
        return external_ns(alias, path)

    def _in(self, path: str) -> str:
        """Workspace-relative path → container-relative (prefix the subpath base).

        No-op when unscoped. ``""``/``"."`` (the workspace root) map to the base
        itself so ``list``/``index`` target the right subtree.
        """
        if not self._base:
            return path
        rel = path.strip("/")
        if not rel or rel == ".":
            return self._base
        return f"{self._base}/{rel}"

    def _out(self, path: str) -> str:
        """Container-relative path → workspace-relative (strip the subpath base).

        The inverse of :meth:`_in` for results that carry paths (list / grep /
        index). No-op when unscoped; a path already outside the base is returned
        unchanged (defensive — the desktop should only ever return in-subtree paths
        once it scopes by base).
        """
        if not self._base:
            return path
        if path == self._base:
            return ""
        prefix = f"{self._base}/"
        return path[len(prefix) :] if path.startswith(prefix) else path

    async def read(self, path: str) -> str:
        root_id, rel, _ = self._route(path)
        value = await self._channel.request(
            WorkspaceOp.READ, {"path": rel}, root_id=root_id
        )
        return str(value)

    async def write(self, path: str, content: str) -> int:
        root_id, rel, _ = self._route(path, write=True, op="write")
        value = await self._channel.request(
            WorkspaceOp.WRITE, {"path": rel, "content": content}, root_id=root_id
        )
        self._dirty = True
        return int(value)

    async def append(self, path: str, content: str) -> int:
        root_id, rel, _ = self._route(path, write=True, op="append")
        value = await self._channel.request(
            WorkspaceOp.APPEND, {"path": rel, "content": content}, root_id=root_id
        )
        self._dirty = True
        return int(value)

    async def read_bytes(self, path: str) -> bytes:
        # The desktop returns base64 (JSON has no byte type); decode back to raw.
        root_id, rel, _ = self._route(path)
        value = await self._channel.request(
            WorkspaceOp.READ_BYTES, {"path": rel}, root_id=root_id
        )
        return base64.b64decode(str(value))

    async def write_bytes(self, path: str, data: bytes) -> int:
        root_id, rel, _ = self._route(path, write=True, op="write_bytes")
        value = await self._channel.request(
            WorkspaceOp.WRITE_BYTES,
            {"path": rel, "data": base64.b64encode(data).decode("ascii")},
            root_id=root_id,
        )
        self._dirty = True
        return int(value)

    async def list(self, directory: str, pattern: str) -> list[DirEntry]:
        root_id, rel, alias = self._route(directory)
        value = await self._channel.request(
            WorkspaceOp.LIST, {"directory": rel, "pattern": pattern}, root_id=root_id
        )
        return [
            DirEntry(
                path=self._out_routed(str(e["path"]), alias),
                is_dir=bool(e["is_dir"]),
            )
            for e in (value or [])
        ]

    async def read_lines(
        self, path: str, *, offset: int = 1, limit: int | None = None
    ) -> ReadLinesResult:
        root_id, rel, _ = self._route(path)
        value = await self._channel.request(
            WorkspaceOp.READ_LINES,
            {"path": rel, "offset": offset, "limit": limit},
            root_id=root_id,
        )
        value = value or {}
        return ReadLinesResult(
            lines=[str(line) for line in value.get("lines", [])],
            start_line=int(value.get("start_line", offset)),
            end_line=int(value.get("end_line", offset - 1)),
            total_lines=int(value.get("total_lines", 0)),
        )

    async def list_tree(
        self,
        directory: str,
        *,
        pattern: str = "*",
        max_depth: int = 3,
        max_entries: int = 200,
    ) -> TreeResult:
        root_id, rel, alias = self._route(directory)
        value = await self._channel.request(
            WorkspaceOp.LIST_TREE,
            {
                "directory": rel,
                "pattern": pattern,
                "max_depth": max_depth,
                "max_entries": max_entries,
            },
            root_id=root_id,
        )
        value = value or {}
        return TreeResult(
            entries=[
                TreeEntry(
                    path=self._out_routed(str(e["path"]), alias),
                    is_dir=bool(e["is_dir"]),
                    depth=int(e["depth"]),
                )
                for e in value.get("entries", [])
            ],
            truncated=bool(value.get("truncated", False)),
            elided_count=int(value.get("elided_count", 0)),
        )

    async def index_files(
        self, cap: int | None = None, *, order: str = "path"
    ) -> tuple[list[str], bool]:
        # The desktop indexes the bound local root (its fsApi.listFiles walk: ignore
        # dirs pruned, capped) and returns {paths, truncated}, so @ mentions + the
        # worker manifest see the same flat view as cloud. ``order`` selects the sort
        # ("path" alphabetical for @, "recent" newest-first for the manifest budget).
        # ``base`` scopes the walk to this workspace's subtree (工作区对称化 D1a) so a
        # shared container root indexes only this workspace; returned paths are
        # stripped back to workspace-relative. Read-only → not dirty.
        value = await self._channel.request(
            WorkspaceOp.INDEX_FILES, {"cap": cap, "order": order, "base": self._in(".")}
        )
        value = value or {}
        paths = [self._out(str(p)) for p in value.get("paths", [])]
        return paths, bool(value.get("truncated", False))

    async def mkdir(self, path: str) -> None:
        root_id, rel, _ = self._route(path, write=True, op="mkdir")
        await self._channel.request(WorkspaceOp.MKDIR, {"path": rel}, root_id=root_id)
        self._dirty = True

    async def delete(self, path: str, *, permanent: bool = False) -> None:
        root_id, rel, _ = self._route(
            path, write=True, op="delete", permanent=permanent
        )
        await self._channel.request(
            WorkspaceOp.DELETE,
            {"path": rel, "permanent": permanent},
            root_id=root_id,
        )
        self._dirty = True

    async def copy(self, src: str, dst: str) -> None:
        src_root, src_rel, src_alias = self._route(src, write=False)
        dst_root, dst_rel, dst_alias = self._route(dst, write=True, op="copy")
        if src_alias != dst_alias or src_root != dst_root:
            raise OutsideWorkspace("不能跨会话授权目录与工作区复制文件")
        await self._channel.request(
            WorkspaceOp.COPY, {"src": src_rel, "dst": dst_rel}, root_id=src_root
        )
        self._dirty = True

    async def move(self, src: str, dst: str) -> None:
        src_root, src_rel, src_alias = self._route(src, write=True, op="move")
        dst_root, dst_rel, dst_alias = self._route(dst, write=True, op="move")
        if src_alias != dst_alias or src_root != dst_root:
            raise OutsideWorkspace("不能跨会话授权目录与工作区移动文件")
        await self._channel.request(
            WorkspaceOp.MOVE, {"src": src_rel, "dst": dst_rel}, root_id=src_root
        )
        self._dirty = True

    async def replace(self, path: str, old: str, new: str, *, all_: bool) -> ReplaceOutcome:
        root_id, rel, _ = self._route(path, write=True, op="replace")
        value = await self._channel.request(
            WorkspaceOp.REPLACE,
            {"path": rel, "old": old, "new": new, "all": all_},
            root_id=root_id,
        )
        self._dirty = True
        first_line = value.get("first_line")
        return ReplaceOutcome(
            count=int(value["count"]),
            first_line=None if first_line is None else int(first_line),
        )

    async def code_search(
        self,
        query: str,
        *,
        language: str | None = None,
        path_prefix: str = ".",
        max_results: int = 10,
    ) -> CodeSearchResult:
        manager = self._get_index_manager()
        return await manager.search(
            query,
            language=language,
            path_prefix=path_prefix,
            max_results=max_results,
        )

    async def ensure_code_index(self, *, force: bool = False) -> bool:
        manager = self._get_index_manager()
        return await manager.ensure_index(self, force=force)

    async def grep(self, query: GrepQuery) -> GrepResult:
        root_id, rel, alias = self._route(query.directory)
        value = await self._channel.request(
            WorkspaceOp.GREP,
            {
                "pattern": query.pattern,
                "directory": rel,
                "glob": query.glob,
                "case_insensitive": query.case_insensitive,
                "files_only": query.files_only,
                "max_results": query.max_results,
            },
            root_id=root_id,
        )
        return GrepResult(
            hits=[
                GrepHit(
                    path=self._out_routed(str(h["path"]), alias),
                    line_no=int(h["line_no"]),
                    text=str(h["text"]),
                )
                for h in value.get("hits", [])
            ],
            file_counts=[
                (self._out_routed(str(fc[0]), alias), int(fc[1]))
                for fc in value.get("file_counts", [])
            ],
            total_matches=int(value.get("total_matches", 0)),
            truncated=bool(value.get("truncated", False)),
        )

    async def execute(self, req: ExecutionRequest) -> ExecutionResult:
        # cwd is the desktop's job (it runs code in the bound local directory). It is
        # sent only as a workspace subtree hint (``cwd`` = the subpath base, 工作区
        # 对称化 D1a) so a scoped workspace runs code in its own dir rather than the
        # shared container root; empty = the root (current behavior). Marked dirty
        # conservatively — executed code commonly writes artifacts and the backend
        # cannot introspect what ran (mirrors ServerWorkspace.execute).
        #
        # W3: pass conversation_id + external root_ids so the desktop injects
        # ``AGENTCORE_EXTERNAL_<ALIAS>`` abs paths into the subprocess env — absolute
        # paths never enter the model prompt.
        self._dirty = True
        external_roots = {
            alias: m.root_id
            for alias, m in self._mounts.items()
            if m.root_id and m.mode != "organize"
        }
        value: dict[str, Any] = await self._channel.request(
            WorkspaceOp.EXECUTE,
            {
                "code": req.code,
                "language": req.language,
                "timeout_seconds": req.timeout_seconds,
                "memory_limit_mb": req.memory_limit_mb,
                "stdin": req.stdin,
                "cwd": self._base,
                "conversation_id": self._channel.conversation_id,
                "external_roots": external_roots,
            },
            # Outlive the desktop's own execution timeout (the authoritative kill)
            # by the slack, so a long but legal run is not cut off by the flat
            # file-op deadline — only a truly gone desktop trips the transport.
            timeout=float(req.timeout_seconds) + self._execute_timeout_slack,
        )
        return ExecutionResult(
            success=bool(value["success"]),
            stdout=str(value.get("stdout", "")),
            stderr=str(value.get("stderr", "")),
            exit_code=int(value.get("exit_code", 0)),
            duration_ms=int(value.get("duration_ms", 0)),
        )
