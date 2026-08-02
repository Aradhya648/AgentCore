"""Workspace staging for the gVisor sandbox — 产物写回 (copy-in / copy-out).

For **non-install** writable executions, gVisor does not get a writable handle on
the canonical workspace. Each run receives a per-run COPY (staged under the OCI
bundle dir, seeded into a tmpfs ``/workspace``); after the process completes,
new or changed regular files are copied back under explicit caps
(``ExecutionResult.written_files``).

**Install exception** (``registry_egress``) lives in ``gvisor.py``: rw-bind the
persistent workspace and skip this module's copy-out / base64 wrap. This file
still skips ``node_modules`` on write-back for any residual staging path.

Why copy-in/copy-out for the default writable path (安全权限与治理.md §五):

- **runsc overlay**: the upper layer lives in the sandbox's internal filestore,
  not an extractable directory tree — artifacts could not be recovered after
  the container exits.
- **host overlayfs**: mounting requires privileges the non-root API container
  does not have.
- **direct rw bind of the real workspace** (general case): loses blast-radius
  control and audit surface — rejected for ordinary writable runs. Install is
  the only product-approved exception (see ``gvisor`` module docstring).

Guards on the write-back leg: symlinks are never staged nor copied back,
``AgentCore/{index,trash,baselines}`` (path-aware internal zones) are excluded
both ways — while ``AgentCore/{规则,记忆,文档}`` **must** be staged — every
destination must resolve inside the workspace root, and total bytes / file
count are capped (fail-visible: skipped files are counted and reported).
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from agentcore.core.errors import SandboxError
from agentcore.workspace._paths import is_internal_zone_relpath

# OCI process user for gVisor sandboxes (nobody). Staging dirs are chowned here
# when the host can (root); otherwise chmod grants other+rwX on the ephemeral
# per-run copy only — never the canonical workspace.
SANDBOX_OCI_UID = 65534
SANDBOX_OCI_GID = 65534
_STAGING_DIR_MODE = 0o775
_STAGING_FILE_MODE = 0o664

#: (size, mtime_ns) fingerprint per workspace-relative path.
TreeState = dict[str, tuple[int, int]]


@dataclass(frozen=True)
class WriteBackReport:
    """Outcome of one copy-out leg."""

    written: list[str] = field(default_factory=list)
    #: Files that changed but were NOT copied back (caps / containment / symlink).
    skipped: list[str] = field(default_factory=list)


def _parent_rel(rel_dir: Path) -> str:
    return "" if not rel_dir.parts else rel_dir.as_posix()


def _prune_internal_and_symlinks(dirpath: str, dirnames: list[str], *, root: Path) -> None:
    """Prune AgentCore internal zones + symlinked dirs in-place for ``os.walk``.

    Does **not** apply ``IGNORED_DIRS`` (node_modules / ``out`` / …) — staging
    still copies the full workspace except path-aware internal zones.
    """
    rel_dir = Path(dirpath).relative_to(root)
    parent = _parent_rel(rel_dir)
    if is_internal_zone_relpath(parent):
        dirnames[:] = []
        return
    dirnames[:] = [
        d
        for d in dirnames
        if not is_internal_zone_relpath(f"{parent}/{d}" if parent else d)
        and not os.path.islink(os.path.join(dirpath, d))
    ]


def _iter_regular_files(root: Path):
    """Yield ``(rel_posix, abs_path)`` for regular files under ``root``.

    Symlinks (files and dirs) are skipped entirely; AgentCore internal zones
    are pruned (visible ``规则/记忆/文档`` still walk).
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        parent = _parent_rel(rel_dir)
        if is_internal_zone_relpath(parent):
            dirnames[:] = []
            continue
        _prune_internal_and_symlinks(dirpath, dirnames, root=root)
        for name in filenames:
            abs_path = Path(dirpath) / name
            if abs_path.is_symlink():
                continue
            if not abs_path.is_file():
                continue  # sockets / fifos etc.
            yield (rel_dir / name).as_posix(), abs_path


def prepare_bind_tree_for_sandbox(root: Path) -> None:
    """Align a per-run bind-mount tree with the gVisor OCI user (uid/gid 65534).

    Used for both ``/workspace`` staging copies and ``/scratch`` script dirs.
    The canonical workspace stays untouched; only ephemeral bundle paths are
    adjusted. When ``chown`` to ``SANDBOX_OCI_UID`` is allowed (root API), dirs/
    files become 775/664 so the sandbox owner can write and the non-root ``app``
    user can still read artifacts for copy-out. Otherwise (typical prod ``USER
    app`` image) grant other+rwX on the tree so container uid 65534 can write
    via the bind mount without widening anything outside ``root``.
    """
    if sys.platform != "linux":
        return

    def _apply(path: Path, *, is_dir: bool) -> None:
        try:
            os.chown(path, SANDBOX_OCI_UID, SANDBOX_OCI_GID)
            os.chmod(path, _STAGING_DIR_MODE if is_dir else _STAGING_FILE_MODE)
        except PermissionError:
            # Non-root API (USER app): cannot chown to 65534. PoC + prod rootless
            # runsc require world-writable ephemeral bind trees — scoped to this
            # per-run bundle path only, never the canonical workspace.
            os.chmod(path, 0o777 if is_dir else 0o666)

    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            _apply(Path(dirpath) / name, is_dir=False)
        for name in dirnames:
            _apply(Path(dirpath) / name, is_dir=True)
    _apply(root, is_dir=True)


def snapshot_tree(root: Path) -> TreeState:
    """Fingerprint every regular file under ``root`` (pre-execution baseline)."""
    state: TreeState = {}
    for rel, abs_path in _iter_regular_files(root):
        st = abs_path.stat()
        state[rel] = (st.st_size, st.st_mtime_ns)
    return state


def stage_workspace(src: Path, dst: Path, *, max_bytes: int) -> TreeState:
    """Copy the workspace into the staging dir; return the staged baseline.

    Preserves directory structure (including empty dirs) and file metadata.
    Raises :class:`SandboxError` with an explainable message when the workspace
    exceeds ``max_bytes`` — better a clear refusal than a silently partial
    sandbox view.
    """
    total = 0
    dst.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel_dir = Path(dirpath).relative_to(src)
        parent = _parent_rel(rel_dir)
        if is_internal_zone_relpath(parent):
            dirnames[:] = []
            continue
        _prune_internal_and_symlinks(dirpath, dirnames, root=src)
        (dst / rel_dir).mkdir(parents=True, exist_ok=True)
        for name in filenames:
            src_file = Path(dirpath) / name
            if src_file.is_symlink() or not src_file.is_file():
                continue
            total += src_file.stat().st_size
            if total > max_bytes:
                raise SandboxError(
                    f"工作区过大（超过 {max_bytes // (1024 * 1024)}MB），"
                    "无法载入云端沙箱执行。请缩小工作区（清理大文件）后重试，"
                    "或立即发 ask_user 卡（桌面在线时：本会话要跑通 → "
                    "action=bind_local_folder；打开本机目录当项目 → "
                    "action=open_local_project；勿用纯文本询问；bind≠打开项目）"
                    "引导后在本机运行。"
                )
            shutil.copy2(src_file, dst / rel_dir / name)
    prepare_bind_tree_for_sandbox(dst)
    return snapshot_tree(dst)


def collect_changes(staging: Path, before: TreeState) -> list[str]:
    """Workspace-relative paths of files the execution created or modified."""
    changes: list[str] = []
    for rel, abs_path in _iter_regular_files(staging):
        st = abs_path.stat()
        fingerprint = (st.st_size, st.st_mtime_ns)
        if before.get(rel) != fingerprint:
            changes.append(rel)
    changes.sort()
    return changes


def write_back(
    staging: Path,
    workspace: Path,
    changes: list[str],
    *,
    max_bytes: int,
    max_files: int,
) -> WriteBackReport:
    """Copy changed files from staging into the real workspace, under caps.

    Deletions are deliberately NOT propagated (artifact-oriented semantics: an
    execution can add or update files, never silently remove canonical ones).
    Every destination is containment-checked against the workspace root after
    resolving symlinks; violations are skipped and reported, never raised —
    the execution itself already succeeded.
    """
    written: list[str] = []
    skipped: list[str] = []
    ws_root = workspace.resolve()
    budget = max_bytes
    for rel in changes:
        if is_internal_zone_relpath(rel):
            skipped.append(rel)
            continue
        # Packaging install on the staging path must not write node_modules back
        # via copy-out (cloud install uses durable rw-bind instead; this skip
        # remains for non-install staging / residual paths).
        if "node_modules" in PurePosixPath(rel).parts:
            skipped.append(rel)
            continue
        src = staging / rel
        if src.is_symlink() or not src.is_file():
            skipped.append(rel)
            continue
        if len(written) >= max_files:
            skipped.append(rel)
            continue
        size = src.stat().st_size
        if size > budget:
            skipped.append(rel)
            continue
        dest = workspace / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Containment after resolving the parent (a pre-existing symlinked dir
        # inside the workspace must not let a write escape the root).
        resolved_parent = dest.parent.resolve()
        if resolved_parent != ws_root and ws_root not in resolved_parent.parents:
            skipped.append(rel)
            continue
        if dest.exists() and (dest.is_symlink() or not dest.is_file()):
            skipped.append(rel)
            continue
        shutil.copy2(src, dest)
        budget -= size
        written.append(rel)
    return WriteBackReport(written=written, skipped=skipped)
