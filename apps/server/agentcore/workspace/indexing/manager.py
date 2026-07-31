"""Index manager — incremental build + BM25 search (query path is ensure-free)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agentcore.workspace._paths import IGNORED_DIRS, is_internal_zone_relpath
from agentcore.workspace.indexing.bm25 import BM25Index
from agentcore.workspace.indexing.chunker import chunk_file, detect_language, snippet_preview
from agentcore.workspace.protocol import (
    CodeChunk,
    CodeIndexStatus,
    CodeSearchResult,
    PathNotFound,
    WorkspaceBackend,
    WorkspaceError,
)
from agentcore.workspace.stage_dirs import INDEX_REL

logger = logging.getLogger(__name__)

_INDEX_DB_NAME = "code_search.db"
_MAX_INDEX_FILES = 5000
_SKIP_DIRS = IGNORED_DIRS  # name-only noise; internal zones via path check


class IndexManager:
    """Builds and queries the workspace BM25 code index.

    File contents are read through ``WorkspaceBackend`` (not direct disk), so the
    same manager works for ``ServerWorkspace`` and channel-backed ``LocalWorkspace``.
    ``index_dir`` holds the SQLite DB; for local disk workspaces this is typically
    ``<workspace>/AgentCore/index``.

    Build/refresh belongs to ``IndexMaintainer`` (or synchronous ``ensure_index``
    for tests). ``search`` never triggers a build.
    """

    def __init__(self, index_dir: str) -> None:
        self._index_dir = str(Path(index_dir))
        self._bm25: BM25Index | None = None
        self._index_truncated = False
        self._last_ensure_complete = False
        self._building = False
        self._content_dirty = False

    @classmethod
    def for_workspace_root(cls, workspace_root: str) -> IndexManager:
        """Index beside a real workspace root (``AgentCore/index``)."""
        return cls(str(Path(workspace_root) / Path(*INDEX_REL.split("/"))))

    def _get_bm25(self) -> BM25Index:
        if self._bm25 is None:
            db_path = os.path.join(self._index_dir, _INDEX_DB_NAME)
            self._bm25 = BM25Index(db_path)
        return self._bm25

    def set_building(self, building: bool) -> None:
        self._building = building

    @property
    def building(self) -> bool:
        return self._building

    def mark_content_dirty(self) -> None:
        """Workspace files changed since the last completed ensure."""
        self._content_dirty = True

    def index_status(self) -> CodeIndexStatus:
        """Compute readiness without running ensure.

        ``BUILDING`` only when no completed ensure exists yet. A refresh of an
        already-built index stays ``READY`` / ``STALE`` so query keeps serving.
        """
        if self._building and not self._last_ensure_complete:
            return CodeIndexStatus.BUILDING
        if not self._last_ensure_complete or self._index_truncated or self._content_dirty:
            return CodeIndexStatus.STALE
        return CodeIndexStatus.READY

    async def ensure_index(self, backend: WorkspaceBackend, *, force: bool = False) -> bool:
        """Ensure the index is up to date. Returns whether any file was re-indexed."""
        bm25 = self._get_bm25()
        paths, truncated = await self._collect_indexable_paths(backend)
        self._index_truncated = truncated

        indexed_paths = await bm25.list_indexed_paths()
        current_set = set(paths)
        updated = False

        for stale_path in indexed_paths - current_set:
            await bm25.remove_file(stale_path)
            updated = True

        for path in paths:
            try:
                text = await backend.read(path)
            except PathNotFound:
                if path in indexed_paths:
                    await bm25.remove_file(path)
                    updated = True
                continue
            except WorkspaceError as exc:
                logger.debug("skip indexing %s: %s", path, exc)
                continue

            digest = bm25.content_hash(text)
            if not force:
                existing = await bm25.get_file_hash(path)
                if existing == digest:
                    continue

            language = detect_language(path)
            chunks = await chunk_file(path, text, language)
            await bm25.upsert_file(path, text, chunks)
            updated = True

        self._last_ensure_complete = not truncated
        self._content_dirty = False
        return updated

    async def _collect_indexable_paths(self, backend: WorkspaceBackend) -> tuple[list[str], bool]:
        paths, truncated = await backend.index_files(cap=_MAX_INDEX_FILES)
        filtered = [p for p in paths if not _should_skip_path(p)]
        if len(filtered) < len(paths):
            truncated = True
        return filtered, truncated

    async def search(
        self,
        query: str,
        *,
        language: str | None = None,
        path_prefix: str = ".",
        max_results: int = 10,
    ) -> CodeSearchResult:
        bm25 = self._get_bm25()
        hits = await bm25.search(
            query,
            language=language,
            path_prefix=path_prefix,
            limit=max(1, max_results),
        )

        chunks: list[CodeChunk] = []
        scores: list[float] = []
        for raw, score in hits:
            chunks.append(
                CodeChunk(
                    path=raw.path,
                    symbol=raw.symbol,
                    symbol_type=raw.symbol_type,
                    start_line=raw.start_line,
                    end_line=raw.end_line,
                    language=raw.language,
                    snippet=snippet_preview(raw.content),
                )
            )
            scores.append(score)

        status = self.index_status()
        return CodeSearchResult(
            chunks=chunks,
            scores=scores,
            index_status=status,
            index_stale=status != CodeIndexStatus.READY,
        )


def _should_skip_path(path: str) -> bool:
    if is_internal_zone_relpath(path):
        return True
    parts = path.replace("\\", "/").split("/")
    return any(part in _SKIP_DIRS for part in parts)
