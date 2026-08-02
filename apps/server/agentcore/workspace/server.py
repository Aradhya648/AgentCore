"""ServerWorkspace — files and code execution on the server (cloud mode).

The first ``WorkspaceBackend`` implementation. It owns a root directory on the
server and a ``SandboxProvider`` for code execution. All filesystem operations
resolve through ``resolve_safe_path`` (the traversal guard, now internal to the
backend), and ``execute`` delegates to the sandbox with ``cwd`` set to the root
so executed code sees the workspace files — fixing the long-standing bug where
``code_execute`` ran in a throwaway temp dir disconnected from file tools.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Literal

from agentcore.tools.sandbox.protocol import (
    ExecutionRequest,
    ExecutionResult,
    SandboxProvider,
)
from agentcore.workspace._paths import (
    is_access_denied_oserror,
    is_ignored_dir_entry,
    is_ignored_file_name,
    is_system_ignored_file_name,
    resolve_safe_path,
)
from agentcore.workspace.channel import WorkspaceChannel
from agentcore.workspace.external_mounts import (
    ExternalMount,
    build_external_env,
    external_mutation_allowed,
    external_ns,
    parse_external_path,
    route_external,
)
from agentcore.workspace.indexing.maintainer import IndexMaintainer
from agentcore.workspace.indexing.manager import IndexManager
from agentcore.workspace.limits import FILE_TOO_LARGE_DETAIL, WORKSPACE_READ_MAX_BYTES
from agentcore.workspace.local import LocalWorkspace
from agentcore.workspace.locks import workspace_lock
from agentcore.workspace.protocol import (
    AlreadyExists,
    AmbiguousMatch,
    CodeSearchResult,
    DirEntry,
    GrepQuery,
    GrepResult,
    NoMatch,
    NotADirectory,
    NotAFile,
    NotUTF8,
    OutsideWorkspace,
    PathNotFound,
    ReadLinesResult,
    ReplaceOutcome,
    TreeEntry,
    TreeResult,
    WorkspaceIOError,
)
from agentcore.workspace.rg_grep import run_grep_rg
from agentcore.workspace.shared_mounts import (
    SharedMount,
    SharedMountMode,
    parse_shared_path,
    readonly_write_error,
    revoked_error,
    route_shared,
    shared_ns,
)
from agentcore.workspace.shared_paths import (
    shared_workspace_root_path,
    shared_workspace_storage_key,
)
from agentcore.workspace.text_replace import (
    TextReplaceAmbiguous,
    TextReplaceNoMatch,
    apply_text_replace,
)
from agentcore.workspace.trash import is_internal_zone_path, soft_delete_to_trash

_MAX_LIST_ENTRIES = 100
_MAX_INDEX_FILES = 5000  # @ mention flat index cap (mirrors desktop LIST_FILES_CAP)


def _posix(rel: str) -> str:
    return rel.replace(os.sep, "/")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp file in the same dir + rename).

    Avoids leaving a half-written or truncated file if the process dies mid-write
    — the whole point of an edit tool is to never corrupt the user's file.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_str_replace_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class ServerWorkspace:
    """``WorkspaceBackend`` backed by a directory + sandbox on the host machine.

    ``location`` defaults to ``"server"`` (an isolated cloud sandbox — workers run
    un-gated). The sidecar reuses this exact backend but passes ``location="local"``:
    there the engine runs ON the user's machine and ``root`` IS their real disk, so a
    delegated worker's ``file_write`` / ``code_execute`` needs the same consent the
    cloud's local mode demands — the gate keys off ``backend.location == "local"``
    (see ``delegate.py`` worker_gate, ``pipeline.py`` revise_gate). Primary-root ops
    use direct ``Path`` I/O either way. Cloud sessions with W3/organize grants (no
    ``abs_path``) additionally attach a ``WorkspaceChannel`` and route **only**
    ``external/<alias>/…`` via per-op ``root_id`` (same transport as
    ``LocalWorkspace``) — ``location`` stays ``"server"`` so worker_gate stays off.
    """

    def __init__(
        self,
        root: Path,
        sandbox: SandboxProvider,
        *,
        root_label: str = "workspace",
        location: Literal["server", "local"] = "server",
    ) -> None:
        self._root = root
        self._sandbox = sandbox
        self.root_label = root_label
        self.location: Literal["server", "local"] = location
        # Flips True on the first mutating op so the service snapshots only
        # workspaces a turn actually changed (see WorkspaceBackend.dirty).
        self._dirty = False
        self._index_manager: IndexManager | None = None
        self._index_maintainer: IndexMaintainer | None = None
        # W3 session mounts (``external/<alias>/…``). Sidecar sets ``abs_path``;
        # cloud grants carry ``root_id`` only and need ``_external_bridge``.
        self._mounts: dict[str, ExternalMount] = {}
        # Desktop channel bridge for cloud external-only ops (per-op root_id).
        self._external_bridge: LocalWorkspace | None = None
        # Shared-space cloud second roots (``shared/<alias>/…``).
        self._shared_mounts: dict[str, SharedMount] = {}
        # Realtime membership gate: space_id → current mount mode, or None if gone.
        self._shared_gate: Callable[[str], Awaitable[SharedMountMode | None]] | None = None
        # Optional hook after a successful shared mutation (firehose / event log).
        self._on_shared_mutation: (
            Callable[[str, str, str], Awaitable[None]] | None
        ) = None  # (space_id, action, path)

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _mark_mutated(self) -> None:
        """Snapshot dirty + invalidate code index (schedule background refresh)."""
        self._dirty = True
        if self._index_manager is not None:
            self._index_manager.mark_content_dirty()
        if self._index_maintainer is not None:
            self._index_maintainer.schedule()

    def start_code_index_maintenance(self) -> None:
        """Kick coalesced background ensure (turn / sidecar entry)."""
        manager = self._get_index_manager()
        if self._index_maintainer is None:
            self._index_maintainer = IndexMaintainer(manager, self)
        self._index_maintainer.schedule()

    def attach_external_mounts(self, mounts: dict[str, ExternalMount]) -> None:
        """Attach session-scoped external mounts for this turn (W3 / organize)."""
        self._mounts = dict(mounts)
        if self._external_bridge is not None:
            self._external_bridge.attach_external_mounts(self._mounts)

    def attach_external_channel(self, channel: WorkspaceChannel) -> None:
        """Attach a desktop channel for cloud ``external/`` ops (root_id only grants).

        Does not flip ``location`` — cloud workers stay ungated; desktop pathGuard +
        organize whitelist + plan card remain the authorization surface.
        """
        bridge = LocalWorkspace(channel, root_label=self.root_label)
        bridge.attach_external_mounts(self._mounts)
        self._external_bridge = bridge

    def attach_shared_mounts(
        self,
        mounts: dict[str, SharedMount],
        *,
        gate: Callable[[str], Awaitable[SharedMountMode | None]] | None = None,
        on_mutation: Callable[[str, str, str], Awaitable[None]] | None = None,
    ) -> None:
        """Attach session-scoped shared-space mounts (cloud second root)."""
        self._shared_mounts = dict(mounts)
        self._shared_gate = gate
        self._on_shared_mutation = on_mutation

    def _external_needs_channel(self, *paths: str) -> bool:
        """True when any path is ``external/`` without ``abs_path`` (desktop channel).

        Unknown aliases raise ``PathNotFound`` immediately. Paths with ``abs_path``
        (sidecar) stay on direct Path I/O.
        """
        needs = False
        for path in paths:
            if parse_external_path(path) is None:
                continue
            routed = route_external(path, self._mounts)
            if routed is None:
                raise PathNotFound(path)
            if not routed.mount.abs_path:
                needs = True
        return needs

    def _require_external_bridge(self) -> LocalWorkspace:
        if self._external_bridge is None:
            raise WorkspaceIOError("会话授权目录在本机引擎外不可直读")
        return self._external_bridge

    @property
    def root(self) -> Path:
        """The server-side workspace directory (used by the snapshot path)."""
        return self._root

    async def _gate_shared(self, path: str, *, write: bool) -> None:
        """Realtime role check for ``shared/<alias>/…`` (tool-call granularity)."""
        if parse_shared_path(path) is None:
            return
        routed = route_shared(path, self._shared_mounts)
        if routed is None:
            raise PathNotFound(path)
        mode: SharedMountMode | None = routed.mount.mode
        if self._shared_gate is not None:
            mode = await self._shared_gate(routed.mount.space_id)
        if mode is None:
            raise OutsideWorkspace(revoked_error(path))
        if write and mode == "readonly":
            raise OutsideWorkspace(readonly_write_error(path))

    @asynccontextmanager
    async def _maybe_shared_lock(self, path: str):
        """Space-level lock for Agent (and human) writes to a shared mount."""
        routed = route_shared(path, self._shared_mounts) if parse_shared_path(path) else None
        if routed is None:
            yield
            return
        async with workspace_lock(shared_workspace_storage_key(routed.mount.space_id)):
            yield

    async def _emit_shared_mutation(self, path: str, action: str) -> None:
        if self._on_shared_mutation is None or parse_shared_path(path) is None:
            return
        routed = route_shared(path, self._shared_mounts)
        if routed is None:
            return
        await self._on_shared_mutation(routed.mount.space_id, action, path)

    def _safe(
        self,
        rel: str,
        *,
        write: bool = False,
        op: str | None = None,
        permanent: bool = False,
    ) -> Path:
        shared_parsed = parse_shared_path(rel)
        if shared_parsed is not None:
            routed = route_shared(rel, self._shared_mounts)
            if routed is None:
                raise PathNotFound(rel)
            if write and routed.mount.mode == "readonly":
                # Sync fallback when gate wasn't awaited yet (should be gated first).
                raise OutsideWorkspace(readonly_write_error(rel))
            mount_root = shared_workspace_root_path(routed.mount.space_id)
            mount_root.mkdir(parents=True, exist_ok=True)
            mount_rel = routed.rel if routed.rel not in ("", ".") else "."
            resolved = resolve_safe_path(mount_root, mount_rel if mount_rel != "." else ".")
            if resolved is None:
                if mount_rel in ("", "."):
                    return mount_root.resolve()
                raise OutsideWorkspace(rel)
            return resolved
        parsed = parse_external_path(rel)
        if parsed is not None:
            routed = route_external(rel, self._mounts)
            if routed is None:
                raise PathNotFound(rel)
            if write:
                err = external_mutation_allowed(
                    routed.mount,
                    op or "write",
                    path=rel,
                    permanent=permanent,
                )
                if err:
                    raise OutsideWorkspace(err)
            if not routed.mount.abs_path:
                raise WorkspaceIOError("会话授权目录在本机引擎外不可直读")
            mount_root = Path(routed.mount.abs_path)
            mount_rel = routed.rel if routed.rel not in ("", ".") else "."
            # Same guard algorithm — separate root, not a weakened boundary.
            resolved = resolve_safe_path(mount_root, mount_rel if mount_rel != "." else ".")
            if resolved is None:
                # ``"."`` against root: resolve_safe_path(workspace, ".") → workspace
                if mount_rel in ("", "."):
                    return mount_root.resolve()
                raise OutsideWorkspace(rel)
            return resolved
        # Normalize model-supplied absolute root-label paths (``/workspace/x.md`` →
        # ``x.md``) at this single seam before the traversal guard runs — only inputs
        # the guard would already reject can be rescued; ``..`` / other-root paths
        # still fail (see strip_root_label_prefix).
        resolved = resolve_safe_path(self._root, rel, root_label=self.root_label)
        if resolved is None:
            raise OutsideWorkspace(rel)
        return resolved

    def _model_path(self, abs_path: Path, *, logical: str | None = None) -> str:
        """Map an absolute path back to a model-facing relative path.

        Prefer the caller's logical ``external/<alias>/…`` or ``shared/<alias>/…``
        namespace; if that fails (or is absent), reverse-lookup mounts by abs
        containment so a mount file never falls through to
        ``relpath(…, primary_root)`` which would leak ``../``-shaped paths into
        model-visible list/grep output.
        """
        resolved = abs_path.resolve()
        if logical and parse_shared_path(logical) is not None:
            routed = route_shared(logical, self._shared_mounts)
            if routed:
                mount_root = shared_workspace_root_path(routed.mount.space_id).resolve()
                try:
                    rel = resolved.relative_to(mount_root)
                    return shared_ns(routed.mount.alias, _posix(str(rel)))
                except ValueError:
                    pass
        if logical and parse_external_path(logical) is not None:
            routed = route_external(logical, self._mounts)
            if routed and routed.mount.abs_path:
                mount_root = Path(routed.mount.abs_path).resolve()
                try:
                    rel = resolved.relative_to(mount_root)
                    return external_ns(routed.mount.alias, _posix(str(rel)))
                except ValueError:
                    pass
        for mount in self._shared_mounts.values():
            mount_root = shared_workspace_root_path(mount.space_id).resolve()
            try:
                rel = resolved.relative_to(mount_root)
                return shared_ns(mount.alias, _posix(str(rel)))
            except ValueError:
                continue
        for mount in self._mounts.values():
            if not mount.abs_path:
                continue
            mount_root = Path(mount.abs_path).resolve()
            try:
                rel = resolved.relative_to(mount_root)
                return external_ns(mount.alias, _posix(str(rel)))
            except ValueError:
                continue
        return _posix(os.path.relpath(resolved, self._root.resolve()))

    def _get_index_manager(self) -> IndexManager:
        if self._index_manager is None:
            self._index_manager = IndexManager.for_workspace_root(str(self._root.resolve()))
        return self._index_manager

    def _reject_oversized_file(self, target: Path) -> None:
        """Capacity contract: refuse whole-file loads above ``WORKSPACE_READ_MAX_BYTES``.

        Same detail string as desktop Local so the tool layer can mark ``contract_failure``.
        """
        try:
            size = target.stat().st_size
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e
        if size > WORKSPACE_READ_MAX_BYTES:
            raise WorkspaceIOError(FILE_TOO_LARGE_DETAIL)

    async def read(self, path: str) -> str:
        if self._external_needs_channel(path):
            return await self._require_external_bridge().read(path)
        await self._gate_shared(path, write=False)
        target = self._safe(path)
        if not target.exists():
            raise PathNotFound(path)
        if not target.is_file():
            raise NotAFile(path)
        self._reject_oversized_file(target)
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise WorkspaceIOError(str(e)) from e

    async def write(self, path: str, content: str) -> int:
        if self._external_needs_channel(path):
            n = await self._require_external_bridge().write(path, content)
            self._mark_mutated()
            return n
        async with self._maybe_shared_lock(path):
            await self._gate_shared(path, write=True)
            target = self._safe(path, write=True, op="write")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            except OSError as e:
                raise WorkspaceIOError(str(e)) from e
            self._mark_mutated()
            await self._emit_shared_mutation(path, "file_written")
            return len(content)

    async def append(self, path: str, content: str) -> int:
        if self._external_needs_channel(path):
            n = await self._require_external_bridge().append(path, content)
            self._mark_mutated()
            return n
        async with self._maybe_shared_lock(path):
            await self._gate_shared(path, write=True)
            target = self._safe(path, write=True, op="append")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if not target.is_file():
                        raise NotAFile(path)
                    with target.open("a", encoding="utf-8") as fh:
                        fh.write(content)
                else:
                    target.write_text(content, encoding="utf-8")
            except NotAFile:
                raise
            except OSError as e:
                raise WorkspaceIOError(str(e)) from e
            self._mark_mutated()
            await self._emit_shared_mutation(path, "file_written")
            return len(content)

    async def read_bytes(self, path: str) -> bytes:
        if self._external_needs_channel(path):
            return await self._require_external_bridge().read_bytes(path)
        await self._gate_shared(path, write=False)
        target = self._safe(path)
        if not target.exists():
            raise PathNotFound(path)
        if not target.is_file():
            raise NotAFile(path)
        self._reject_oversized_file(target)
        try:
            return target.read_bytes()
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e

    async def write_bytes(self, path: str, data: bytes) -> int:
        if self._external_needs_channel(path):
            n = await self._require_external_bridge().write_bytes(path, data)
            self._mark_mutated()
            return n
        async with self._maybe_shared_lock(path):
            await self._gate_shared(path, write=True)
            target = self._safe(path, write=True, op="write_bytes")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_bytes(target, data)
            except OSError as e:
                raise WorkspaceIOError(str(e)) from e
            self._mark_mutated()
            await self._emit_shared_mutation(path, "file_written")
            return len(data)

    async def read_for_edit(self, path: str) -> tuple[str, int, Literal["lf", "crlf"]]:
        """Read a text file for in-panel editing: ``(text, mtime_ms, eol)``.

        Unlike the preview download (truncated), this returns the **whole** file so
        a later save never drops the tail. Content is newline-normalized to ``\\n``;
        the original EOL is reported so the editor can restore it on write.
        ``mtime_ms`` is the write-time CAS baseline (see :meth:`write_text_cas`).
        Raises ``OutsideWorkspace`` / ``PathNotFound`` / ``NotAFile`` / ``NotUTF8`` /
        ``WorkspaceIOError``.
        """
        await self._gate_shared(path, write=False)
        target = self._safe(path)
        if not target.exists():
            raise PathNotFound(path)
        if not target.is_file():
            raise NotAFile(path)
        self._reject_oversized_file(target)
        try:
            raw = target.read_bytes()
            mtime_ms = target.stat().st_mtime_ns // 1_000_000
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise NotUTF8(path) from e
        eol: Literal["lf", "crlf"] = "crlf" if "\r\n" in text else "lf"
        return text.replace("\r\n", "\n"), mtime_ms, eol

    async def write_text_cas(
        self,
        path: str,
        content: str,
        *,
        baseline_mtime_ms: int,
        eol: Literal["lf", "crlf"],
    ) -> tuple[bool, int]:
        """Conditionally write ``content`` with a write-time CAS on mtime.

        Returns ``(ok, mtime_ms)``: on success ``mtime_ms`` is the new mtime; on a
        **conflict** (``ok`` is False) it is the current disk mtime, so the caller can
        offer "overwrite anyway" using it as the next baseline — we never blind-clobber
        a file changed under us (e.g. by an Agent turn). ``baseline_mtime_ms == 0``
        means "new file": a conflict if something already exists at ``path``. ``\\n``
        is restored to ``eol`` before an atomic (temp + rename) write. Raises
        ``OutsideWorkspace`` / ``NotAFile`` / ``WorkspaceIOError``.

        Best-effort against external writers; callers serialize against same-workspace
        turns via ``workspace_lock`` so an Agent write can't interleave mid-CAS.
        """
        async with self._maybe_shared_lock(path):
            await self._gate_shared(path, write=True)
            target = self._safe(path, write=True, op="write")
            exists = target.exists()
            if exists and not target.is_file():
                raise NotAFile(path)
            try:
                if baseline_mtime_ms == 0:
                    if exists:
                        return False, target.stat().st_mtime_ns // 1_000_000
                elif not exists:
                    return False, 0  # the baseline file was deleted under us
                else:
                    disk_ms = target.stat().st_mtime_ns // 1_000_000
                    if disk_ms != baseline_mtime_ms:
                        return False, disk_ms
                body = content.replace("\n", "\r\n") if eol == "crlf" else content
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_bytes(target, body.encode("utf-8"))
                new_ms = target.stat().st_mtime_ns // 1_000_000
            except OSError as e:
                raise WorkspaceIOError(str(e)) from e
            self._mark_mutated()
            await self._emit_shared_mutation(path, "file_written")
            return True, new_ms

    async def list(self, directory: str, pattern: str) -> list[DirEntry]:
        if self._external_needs_channel(directory):
            return await self._require_external_bridge().list(directory, pattern)
        await self._gate_shared(directory, write=False)
        base = self._safe(directory)
        if not base.is_dir():
            raise NotADirectory(directory)
        try:
            entries = sorted(base.glob(pattern))[:_MAX_LIST_ENTRIES]
            parent_rel = directory.replace("\\", "/").strip("/")
            if parent_rel in ("", "."):
                parent_rel = ""
            out: list[DirEntry] = []
            for entry in entries:
                # Name-first ignore — avoid touching locked noise dirs (e.g. Windows
                # ``.pytest_tmp``) before ``is_dir`` / ``is_file``.
                if is_ignored_dir_entry(parent_rel=parent_rel, name=entry.name):
                    continue
                try:
                    is_dir = entry.is_dir()
                    is_file = entry.is_file()
                except OSError as e:
                    if is_access_denied_oserror(e):
                        continue
                    raise WorkspaceIOError(str(e)) from e
                if is_file and is_system_ignored_file_name(entry.name):
                    continue
                # UI REST shares ``list`` — only system noise; AI ``file_list``
                # applies AI-noise filtering in the tool layer.
                out.append(
                    DirEntry(
                        path=self._model_path(entry, logical=directory),
                        is_dir=is_dir,
                    )
                )
            return out
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e

    async def read_lines(
        self, path: str, *, offset: int = 1, limit: int | None = None
    ) -> ReadLinesResult:
        if self._external_needs_channel(path):
            return await self._require_external_bridge().read_lines(
                path, offset=offset, limit=limit
            )
        target = self._safe(path)
        if not target.exists():
            raise PathNotFound(path)
        if not target.is_file():
            raise NotAFile(path)
        self._reject_oversized_file(target)
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise WorkspaceIOError(str(e)) from e

        lines = content.splitlines()
        total = len(lines)
        start_idx = max(0, offset - 1)
        if start_idx >= total:
            return ReadLinesResult(
                lines=[],
                start_line=offset,
                end_line=offset - 1,
                total_lines=total,
            )

        end_idx = total if limit is None else min(total, start_idx + limit)
        selected = lines[start_idx:end_idx]
        return ReadLinesResult(
            lines=selected,
            start_line=start_idx + 1,
            end_line=end_idx,
            total_lines=total,
        )

    async def list_tree(
        self,
        directory: str,
        *,
        pattern: str = "*",
        max_depth: int = 3,
        max_entries: int = 200,
    ) -> TreeResult:
        if self._external_needs_channel(directory):
            return await self._require_external_bridge().list_tree(
                directory,
                pattern=pattern,
                max_depth=max_depth,
                max_entries=max_entries,
            )
        base = self._safe(directory)
        if not base.is_dir():
            raise NotADirectory(directory)

        entries: list[TreeEntry] = []
        truncated = False
        elided_count = 0
        warnings: list[str] = []
        name_filter = pattern or "*"

        def walk(dir_path: Path, depth: int, *, is_root: bool) -> None:
            nonlocal truncated, elided_count
            if depth > max_depth:
                return
            try:
                children = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())
            except OSError as e:
                if not is_root and is_access_denied_oserror(e):
                    try:
                        rel = dir_path.resolve().relative_to(self._root.resolve()).as_posix()
                    except ValueError:
                        rel = dir_path.name
                    if rel == ".":
                        rel = directory if directory not in ("", ".") else "."
                    warnings.append(f"跳过无权限目录：{rel}")
                    return
                raise WorkspaceIOError(str(e)) from e

            try:
                parent_rel = dir_path.resolve().relative_to(self._root.resolve()).as_posix()
            except ValueError:
                parent_rel = ""
            if parent_rel == ".":
                parent_rel = ""

            for child in children:
                # Name-first prune — do not ``is_dir`` locked ignore-set dirs.
                if is_ignored_dir_entry(parent_rel=parent_rel, name=child.name):
                    continue
                try:
                    is_dir = child.is_dir() and not child.is_symlink()
                    is_file = child.is_file()
                except OSError as e:
                    if is_access_denied_oserror(e):
                        rel = f"{parent_rel}/{child.name}" if parent_rel else child.name
                        warnings.append(f"跳过无权限条目：{rel}")
                        continue
                    raise WorkspaceIOError(str(e)) from e

                if is_file and is_ignored_file_name(child.name):
                    continue

                rel = self._model_path(child, logical=directory)

                if not is_dir and not fnmatch.fnmatch(child.name, name_filter):
                    continue

                if len(entries) >= max_entries:
                    truncated = True
                    elided_count += 1
                    continue

                entries.append(TreeEntry(path=rel, is_dir=is_dir, depth=depth))
                if is_dir and depth < max_depth:
                    walk(child, depth + 1, is_root=False)

        walk(base, 1, is_root=True)
        return TreeResult(
            entries=entries,
            truncated=truncated,
            elided_count=elided_count,
            warnings=warnings,
        )

    async def index_files(
        self, cap: int | None = None, *, order: str = "path"
    ) -> tuple[list[str], bool]:
        """Flat list of file paths for @ mentions (文件中枢统一 F4) + worker manifest.

        Files only, ``IGNORED_DIRS`` pruned, capped at ``cap`` (``truncated`` when
        hit; ``cap=None`` uses the default ``_MAX_INDEX_FILES``) — the cloud
        counterpart to the desktop ``fsApi.listFiles`` that indexes local roots, so @
        and the worker manifest behave the same whether a workspace is cloud or local.
        ``order="path"`` (default) = alphabetical (the @ view); ``order="recent"`` =
        newest-first by mtime (one extra stat/file) for the manifest's relevance budget.
        Noise dirs (``.git`` / ``node_modules`` / …) plus path-aware
        ``AgentCore/{index,trash,baselines}``, and AI-tier
        suffixes (``*.db`` / media / binaries) are pruned — same rule set as
        desktop ``collectWorkspaceFiles`` / ``opIndexFiles``.
        """
        cap = cap or _MAX_INDEX_FILES
        recent = order == "recent"
        root = self._root.resolve()
        collected: list[tuple[str, float]] = []  # (posix_path, mtime); mtime 0 unless recent
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune noise dirs in place so os.walk never descends into them.
            rel_dir = os.path.relpath(dirpath, root)
            parent_rel = "" if rel_dir == "." else rel_dir.replace("\\", "/")
            dirnames[:] = sorted(
                d for d in dirnames if not is_ignored_dir_entry(parent_rel=parent_rel, name=d)
            )
            for fname in sorted(filenames):
                if is_ignored_file_name(fname):
                    continue
                full = Path(dirpath) / fname
                if full.is_symlink() or not full.is_file():
                    continue
                mtime = full.stat().st_mtime if recent else 0.0
                collected.append((_posix(os.path.relpath(full, root)), mtime))
                if len(collected) >= cap:
                    truncated = True
                    break
            if truncated:
                break
        if recent:
            collected.sort(key=lambda pm: pm[1], reverse=True)  # newest first
        else:
            collected.sort(key=lambda pm: pm[0])  # alphabetical
        return [p for p, _ in collected], truncated

    async def mkdir(self, path: str) -> None:
        if self._external_needs_channel(path):
            await self._require_external_bridge().mkdir(path)
            self._mark_mutated()
            return
        async with self._maybe_shared_lock(path):
            await self._gate_shared(path, write=True)
            target = self._safe(path, write=True, op="mkdir")
            # Refuse mkdir of the primary workspace root itself; external mount roots
            # are also "already there" as the grant target.
            if target == self._root.resolve():
                raise OutsideWorkspace(path)
            routed = route_external(path, self._mounts) if parse_external_path(path) else None
            if (
                routed
                and routed.mount.abs_path
                and target == Path(routed.mount.abs_path).resolve()
            ):
                raise OutsideWorkspace(path)
            shared = route_shared(path, self._shared_mounts) if parse_shared_path(path) else None
            if shared and target == shared_workspace_root_path(shared.mount.space_id).resolve():
                raise OutsideWorkspace(path)
            if target.exists():
                raise AlreadyExists(path)
            try:
                target.mkdir(parents=True, exist_ok=False)
            except OSError as e:
                raise WorkspaceIOError(str(e)) from e
            self._mark_mutated()
            await self._emit_shared_mutation(path, "dir_created")

    async def delete(self, path: str, *, permanent: bool = False) -> None:
        if self._external_needs_channel(path):
            await self._require_external_bridge().delete(path, permanent=permanent)
            self._mark_mutated()
            return
        async with self._maybe_shared_lock(path):
            await self._gate_shared(path, write=True)
            target = self._safe(path, write=True, op="delete", permanent=permanent)
            if target == self._root.resolve():
                raise OutsideWorkspace(path)  # never delete the workspace root
            routed = route_external(path, self._mounts) if parse_external_path(path) else None
            if routed and routed.mount.abs_path:
                mount_root = Path(routed.mount.abs_path).resolve()
                if target == mount_root:
                    raise OutsideWorkspace(path)
            else:
                shared = (
                    route_shared(path, self._shared_mounts)
                    if parse_shared_path(path)
                    else None
                )
                if shared:
                    mount_root = shared_workspace_root_path(shared.mount.space_id).resolve()
                    if target == mount_root:
                        raise OutsideWorkspace(path)
                else:
                    mount_root = self._root.resolve()
            if not target.exists():
                raise PathNotFound(path)
            # Soft-delete into AgentCore/trash cannot nest under itself; treat
            # internal zones (index/trash/baselines) as permanent cleanup — not
            # the whole AgentCore/ tree (rules/memory/docs stay soft-deletable).
            hard = permanent or is_internal_zone_path(path)
            try:
                if hard:
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                else:
                    shared_routed = (
                        route_shared(path, self._shared_mounts)
                        if parse_shared_path(path)
                        else None
                    )
                    trash_rel = (
                        routed.rel
                        if routed is not None
                        else (
                            shared_routed.rel
                            if shared_routed is not None
                            else path.replace("\\", "/")
                        )
                    )
                    soft_delete_to_trash(
                        root=mount_root,
                        target=target,
                        original_rel=trash_rel or path.replace("\\", "/"),
                    )
            except OSError as e:
                raise WorkspaceIOError(str(e)) from e
            self._mark_mutated()
            await self._emit_shared_mutation(path, "file_deleted")

    async def copy(self, src: str, dst: str) -> None:
        if self._external_needs_channel(src, dst):
            await self._require_external_bridge().copy(src, dst)
            self._mark_mutated()
            return
        source = self._safe(src, write=False)
        dest = self._safe(dst, write=True, op="copy")
        src_ext = parse_external_path(src)
        dst_ext = parse_external_path(dst)
        if bool(src_ext) != bool(dst_ext):
            raise OutsideWorkspace("不能跨会话授权目录与工作区复制文件")
        if src_ext and dst_ext and src_ext[0] != dst_ext[0]:
            raise OutsideWorkspace("不能跨会话授权目录复制文件")
        if src_ext is None:
            root = self._root.resolve()
            if source == root or dest == root:
                raise OutsideWorkspace(src if source == root else dst)
        if not source.exists():
            raise PathNotFound(src)
        if dest.exists():
            raise AlreadyExists(dst)
        # Refuse copying a directory into itself or a descendant (self-recursion).
        try:
            dest.relative_to(source)
            if source.is_dir():
                raise WorkspaceIOError("不能复制到自身或其子目录")
        except ValueError:
            pass  # dest is not under source — expected
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, dest)
            else:
                shutil.copy2(source, dest)
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e
        self._mark_mutated()

    async def move(self, src: str, dst: str) -> None:
        if self._external_needs_channel(src, dst):
            await self._require_external_bridge().move(src, dst)
            self._mark_mutated()
            return
        source = self._safe(src, write=True, op="move")
        dest = self._safe(dst, write=True, op="move")
        src_ext = parse_external_path(src)
        dst_ext = parse_external_path(dst)
        if bool(src_ext) != bool(dst_ext):
            raise OutsideWorkspace("不能跨会话授权目录与工作区移动文件")
        if src_ext and dst_ext and src_ext[0] != dst_ext[0]:
            raise OutsideWorkspace("不能跨会话授权目录移动文件")
        if src_ext is None:
            root = self._root.resolve()
            if source == root or dest == root:
                raise OutsideWorkspace(src if source == root else dst)
        if not source.exists():
            raise PathNotFound(src)
        if dest.exists():
            raise AlreadyExists(dst)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, dest)
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e
        self._mark_mutated()

    async def replace(self, path: str, old: str, new: str, *, all_: bool) -> ReplaceOutcome:
        if self._external_needs_channel(path):
            outcome = await self._require_external_bridge().replace(
                path, old, new, all_=all_
            )
            self._mark_mutated()
            return outcome
        target = self._safe(path, write=True, op="replace")
        if not target.exists():
            raise PathNotFound(path)
        if not target.is_file():
            raise NotAFile(path)

        try:
            # Read bytes + decode (no newline translation). ``apply_text_replace``
            # keeps exact hits byte-faithful; CRLF↔LF mismatch uses the LF-normalize
            # fallback and restores the file's original eol on write-back.
            content = target.read_bytes().decode("utf-8")
        except UnicodeDecodeError as e:
            raise NotUTF8(path) from e
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e

        result = apply_text_replace(content, old, new, all_=all_)
        if isinstance(result, TextReplaceNoMatch):
            raise NoMatch(path)
        if isinstance(result, TextReplaceAmbiguous):
            raise AmbiguousMatch(result.count)

        try:
            _atomic_write_bytes(target, result.content.encode("utf-8"))
        except OSError as e:
            raise WorkspaceIOError(str(e)) from e

        self._mark_mutated()
        return ReplaceOutcome(count=result.count, first_line=result.first_line)

    async def grep(self, query: GrepQuery) -> GrepResult:
        # Path checks stay on the event loop so OutsideWorkspace / PathNotFound
        # surface immediately. The ripgrep child is awaited with
        # ``create_subprocess_exec`` so a tool-level ``asyncio.wait_for`` /
        # cancellation can kill the process (no silent Python walk fallback).
        if self._external_needs_channel(query.directory):
            return await self._require_external_bridge().grep(query)
        base = self._safe(query.directory)
        if not base.exists():
            raise PathNotFound(query.directory)
        logical = query.directory
        return await run_grep_rg(
            query=query,
            search_root=base,
            workspace_root=self._root,
            model_path=lambda p: self._model_path(p, logical=logical),
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

    async def diagnostics(self, paths: list[str]) -> dict:
        """Cloud has no language-service channel — honest unavailable (no fake tsc)."""
        _ = paths
        return {
            "status": "unavailable",
            "reason": "云端工作区暂不支持语言服务内环诊断",
            "diagnostics": [],
        }

    async def execute(self, req: ExecutionRequest) -> ExecutionResult:
        # Run code in the workspace root so relative file paths resolve against
        # the same files the file tools see.
        #
        # Mark dirty conservatively: the backend can't introspect what the
        # sandbox wrote, and executed code commonly produces artifacts in the
        # workspace, so we treat any run as potentially mutating. The cost is an
        # occasional snapshot of a pure-compute run (cheap, async, post-answer);
        # the alternative — silently missing code-generated files — is worse for
        # a backup feature. Read-only file ops still never set this.
        self._mark_mutated()
        env = dict(req.env or {})
        env.update(build_external_env(self._mounts))
        cwd = str(self._root.resolve())
        # D11′：python 执行与 TestExitCode 同源注入 PYTHONPATH（. + 现存 src/lib）
        if req.language == "python":
            from agentcore.tools.sandbox.pythonpath import merge_pythonpath_into_env

            env = merge_pythonpath_into_env(Path(cwd), env)
        return await self._sandbox.execute(
            replace(req, cwd=cwd, env=env or None)
        )
