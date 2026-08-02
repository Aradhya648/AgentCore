"""WorkspaceBackend Protocol — the single seam for file + execution access.

Every filesystem / code-execution tool talks to a ``WorkspaceBackend`` instead
of touching ``Path`` directly. This is what lets one agent loop run against two
execution platforms without forking the engine:

- ``ServerWorkspace`` — files and execution live on the server (cloud mode).
- ``LocalWorkspace`` — files and execution live on the user's machine, reached
  over the desktop channel (local mode, added later).

Design constraints (pinned now so the contract never breaks under us):

- **Lean.** The backend owns exactly the pair that must share a platform: file
  I/O (axis 1) and code execution (axis 2). Persistence / snapshotting (axis 3)
  is deliberately NOT here — that is a turn-level storage policy handled by a
  separate ``StorageProvider``.
- **Typed failures.** Methods raise ``WorkspaceError`` subclasses instead of
  returning sentinel strings, so the (thin) tool layer can map each failure to
  its exact user-facing message and a remote ``LocalWorkspace`` can serialize
  the failure kind. The tool layer is responsible for catching these.
- **No absolute paths leak.** All inputs and outputs are workspace-relative
  (POSIX) paths; ``root_label`` is the only human-facing name for the root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from agentcore.tools.sandbox.protocol import ExecutionRequest, ExecutionResult


class CodeIndexStatus(StrEnum):
    """Readiness of the BM25 code index relative to the workspace.

    ``code_search`` is query-only; the maintainer owns build/refresh. Callers
    must not treat ``BUILDING`` / ``STALE`` as tool failure — prefer ``grep``
    when the index is not ``READY`` and exactness matters.
    """

    READY = "ready"
    BUILDING = "building"
    STALE = "stale"


class WorkspaceError(Exception):
    """Base for all workspace-backend failures (caught and mapped by tools)."""


class OutsideWorkspace(WorkspaceError):
    """A supplied path resolved outside the workspace root (traversal guard)."""


class PathNotFound(WorkspaceError):
    """The target file or directory does not exist."""


class NotAFile(WorkspaceError):
    """A file was expected but the path is a directory (or other non-file)."""


class NotADirectory(WorkspaceError):
    """A directory was expected but the path is not one."""


class AlreadyExists(WorkspaceError):
    """The destination of a ``move`` already exists (would clobber)."""


class NotUTF8(WorkspaceError):
    """The file is binary / not valid UTF-8 and cannot be edited as text."""


class NoMatch(WorkspaceError):
    """``replace``: ``old`` was not found in the target file."""


class AmbiguousMatch(WorkspaceError):
    """``replace``: ``old`` matched multiple times without ``all_=True``."""

    def __init__(self, count: int, message: str = "") -> None:
        self.count = count
        super().__init__(message or f"{count} matches")


class WorkspaceIOError(WorkspaceError):
    """A low-level I/O failure (read/write) that is not one of the above."""


@dataclass(frozen=True)
class DirEntry:
    """One entry from ``list`` — workspace-relative POSIX path + kind."""

    path: str
    is_dir: bool


@dataclass(frozen=True)
class ReadLinesResult:
    """Bounded slice from ``read_lines`` — 1-based inclusive line range."""

    lines: list[str]
    start_line: int
    end_line: int
    total_lines: int


@dataclass(frozen=True)
class TreeEntry:
    """One node from ``list_tree`` — workspace-relative path + depth."""

    path: str
    is_dir: bool
    depth: int


@dataclass
class TreeResult:
    """Bounded recursive directory listing from ``list_tree``."""

    entries: list[TreeEntry]
    truncated: bool
    elided_count: int
    # Soft skips (e.g. per-dir access denied) — listing still succeeds.
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReplaceOutcome:
    """Result of ``replace``: how many spans changed, and where the first was."""

    count: int
    first_line: int | None = None


@dataclass(frozen=True)
class GrepHit:
    """One content match: workspace-relative POSIX path, 1-based line, text."""

    path: str
    line_no: int
    text: str


@dataclass
class GrepQuery:
    """Inputs for a ``grep`` content search (serializable for remote backends)."""

    pattern: str
    directory: str = "."
    glob: str | None = None
    case_insensitive: bool = False
    files_only: bool = False
    max_results: int = 50


@dataclass
class GrepResult:
    """Bounded result of a ``grep``: line hits, per-file counts, totals, cap."""

    hits: list[GrepHit] = field(default_factory=list)
    file_counts: list[tuple[str, int]] = field(default_factory=list)
    total_matches: int = 0
    truncated: bool = False
    # Soft skips (e.g. rg IO / access denied on one subtree) — search still succeeds.
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CodeChunk:
    """One searchable code block returned by ``code_search``."""

    path: str
    symbol: str | None
    symbol_type: str | None
    start_line: int
    end_line: int
    language: str
    snippet: str


@dataclass
class CodeSearchResult:
    """Bounded semantic-ish search over symbol-level code chunks."""

    chunks: list[CodeChunk] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    index_status: CodeIndexStatus = CodeIndexStatus.STALE
    # True when status is not READY (kept for older call sites / renderers).
    index_stale: bool = False


class WorkspaceBackend(Protocol):
    """File + execution access for one workspace, on one execution platform."""

    location: Literal["server", "local"]
    root_label: str  # human-facing root name for relative-path rendering

    @property
    def dirty(self) -> bool:
        """True once any mutating op (write/replace/execute) ran this turn.

        Read-only on the Protocol (implementations expose ``@property`` over
        an internal flag). Callers snapshot only workspaces a turn actually
        touched (决策⑥: 改过文件的任务才后台备份). Read-only ops
        (read/list/grep) never set it.
        """
        ...

    async def read(self, path: str) -> str:
        """Return the UTF-8 text content of ``path``.

        Raises ``OutsideWorkspace`` / ``PathNotFound`` / ``NotAFile`` /
        ``WorkspaceIOError``.
        """
        ...

    async def write(self, path: str, content: str) -> int:
        """Create or overwrite ``path`` (with parents); return chars written.

        Raises ``OutsideWorkspace`` / ``WorkspaceIOError``.
        """
        ...

    async def append(self, path: str, content: str) -> int:
        """Append ``content`` to ``path`` (create with parents if missing); return chars appended.

        Raises ``OutsideWorkspace`` / ``PathNotFound`` / ``NotAFile`` / ``WorkspaceIOError``.
        """
        ...

    async def read_bytes(self, path: str) -> bytes:
        """Return the raw bytes of ``path`` (binary-safe; for file download).

        The byte-level counterpart of ``read`` for non-text files (images, PDFs,
        archives). Raises ``OutsideWorkspace`` / ``PathNotFound`` / ``NotAFile`` /
        ``WorkspaceIOError``.
        """
        ...

    async def write_bytes(self, path: str, data: bytes) -> int:
        """Create or overwrite ``path`` with raw ``data`` (with parents).

        The byte-level counterpart of ``write`` for binary uploads; returns the
        number of bytes written. Raises ``OutsideWorkspace`` / ``WorkspaceIOError``.
        """
        ...

    async def list(self, directory: str, pattern: str) -> list[DirEntry]:
        """List entries under ``directory`` matching glob ``pattern`` (capped).

        Raises ``OutsideWorkspace`` / ``NotADirectory`` / ``WorkspaceIOError``.
        """
        ...

    async def read_lines(
        self, path: str, *, offset: int = 1, limit: int | None = None
    ) -> ReadLinesResult:
        """Return a 1-based line slice of ``path`` (``limit`` caps rows returned).

        Raises ``OutsideWorkspace`` / ``PathNotFound`` / ``NotAFile`` /
        ``WorkspaceIOError``. When ``offset`` is past EOF, returns empty ``lines``
        with the correct ``total_lines``.
        """
        ...

    async def list_tree(
        self,
        directory: str,
        *,
        pattern: str = "*",
        max_depth: int = 3,
        max_entries: int = 200,
    ) -> TreeResult:
        """Recursively list ``directory`` as a depth-bounded tree (ignore-pruned).

        ``pattern`` filters file names only (directories are always included so the
        tree stays connected). Raises ``OutsideWorkspace`` / ``NotADirectory`` /
        ``WorkspaceIOError``.
        """
        ...

    async def index_files(
        self, cap: int | None = None, *, order: str = "path"
    ) -> tuple[list[str], bool]:
        """Flat, ignore-pruned, capped list of workspace-relative file paths.

        Files only (no directories), ``IGNORED_DIRS`` pruned, capped at ``cap``
        (``truncated`` True when the cap was hit; ``cap=None`` uses the backend default).
        ``order`` picks the sort (and thus what survives truncation): ``"path"``
        (default) is POSIX-alphabetical and stat-free — the @-mention / picker view;
        ``"recent"`` is newest-first by mtime (one stat/file) so a worker manifest spends
        its budget on the most-likely-relevant files in a big tree, not whatever sorts
        first. The shared file-discovery primitive behind @ mentions (文件中枢统一 F4) and
        the worker workspace manifest — so both see the same flat view whether the
        workspace is cloud (``ServerWorkspace``) or local (``LocalWorkspace``, indexed on
        the desktop). Read-only (never sets ``dirty``); an empty / not-yet-promoted
        workspace returns ``([], False)``.
        """
        ...

    async def mkdir(self, path: str) -> None:
        """Create directory ``path`` (with parents).

        Refuses to recreate the root or an existing path. Raises
        ``OutsideWorkspace`` / ``AlreadyExists`` / ``WorkspaceIOError``.
        """
        ...

    async def delete(self, path: str, *, permanent: bool = False) -> None:
        """Delete ``path`` (a file, or a directory and its contents).

        Default is reversible: local Electron channels move to the OS recycle
        bin; cloud / sidecar backends move into ``AgentCore/trash/`` with
        restore metadata. ``permanent=True`` hard-deletes. Refuses to delete
        the workspace root itself. Raises ``OutsideWorkspace`` /
        ``PathNotFound`` / ``WorkspaceIOError``.
        """
        ...

    async def copy(self, src: str, dst: str) -> None:
        """Copy file or directory tree ``src`` to ``dst`` (creating parents).

        Supports binary files and recursive directory trees. Refuses to copy
        the root, overwrite an existing ``dst``, or copy a directory into
        itself / a descendant. Raises ``OutsideWorkspace`` / ``PathNotFound`` /
        ``AlreadyExists`` / ``WorkspaceIOError``.
        """
        ...

    async def move(self, src: str, dst: str) -> None:
        """Move/rename ``src`` to ``dst`` (creating ``dst``'s parents).

        Refuses to move the root or to overwrite an existing ``dst``. Raises
        ``OutsideWorkspace`` / ``PathNotFound`` / ``AlreadyExists`` /
        ``WorkspaceIOError``.
        """
        ...

    async def replace(self, path: str, old: str, new: str, *, all_: bool) -> ReplaceOutcome:
        """Replace exact span(s) ``old`` -> ``new`` in ``path`` atomically.

        Raises ``OutsideWorkspace`` / ``PathNotFound`` / ``NotAFile`` /
        ``NotUTF8`` / ``NoMatch`` / ``AmbiguousMatch`` / ``WorkspaceIOError``.
        Argument validation (empty ``old``, ``old == new``) is the caller's job.
        """
        ...

    async def grep(self, query: GrepQuery) -> GrepResult:
        """Regex-search file contents under ``query.directory`` (bounded).

        ``query.directory`` may be a directory (recursed, ``glob``-filtered) or a
        single file (scanned alone, ``glob`` ignored — rg PATTERN FILE). Raises
        ``OutsideWorkspace`` / ``PathNotFound``. The regex is assumed already
        validated by the caller.
        """
        ...

    async def code_search(
        self,
        query: str,
        *,
        language: str | None = None,
        path_prefix: str = ".",
        max_results: int = 10,
    ) -> CodeSearchResult:
        """BM25 search over the current index snapshot (query-only).

        Read-only (never sets snapshot ``dirty``). Does **not** build or refresh
        the index — that is ``IndexMaintainer`` / ``ensure_code_index``. Returns
        ``index_status`` (``ready`` / ``building`` / ``stale``); when not
        ``ready``, prefer ``grep`` for exact matches.
        """
        ...

    async def ensure_code_index(self, *, force: bool = False) -> bool:
        """Synchronously build or refresh the code-search index (incremental).

        Prefer ``start_code_index_maintenance`` for turn paths — this method is
        for tests and explicit admin refresh. May be slow on first call for large
        workspaces (capped file count). Read-only (never sets snapshot ``dirty``).
        """
        ...

    def start_code_index_maintenance(self) -> None:
        """Kick background index build/refresh (coalesced, non-blocking)."""
        ...

    async def diagnostics(self, paths: list[str]) -> dict[str, Any]:
        """Language-service diagnostics for TS/JS paths (inner verify loop).

        Returns ``{status: "ok"|"unavailable", reason?: str, diagnostics: [...]}``
        where each diagnostic is
        ``{path, line, column, severity, message, code?}``.

        Local backends route to the desktop language service; cloud
        ``ServerWorkspace`` returns ``unavailable`` honestly (never fakes a full
        ``tsc``). Read-only — never sets ``dirty``.
        """
        ...

    async def execute(self, req: ExecutionRequest) -> ExecutionResult:
        """Run code on this workspace's platform, in the workspace directory.

        The backend fills ``req.cwd`` so code sees the workspace files; it then
        delegates to its ``SandboxProvider`` (no separate execution path).
        """
        ...
