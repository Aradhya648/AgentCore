"""Index manager — incremental build + BM25 search."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agentcore.workspace._paths import IGNORED_DIRS
from agentcore.workspace.indexing.bm25 import BM25Index
from agentcore.workspace.indexing.chunker import chunk_file, detect_language, snippet_preview
from agentcore.workspace.protocol import (
    CodeChunk,
    CodeSearchResult,
    PathNotFound,
    WorkspaceBackend,
    WorkspaceError,
)

logger = logging.getLogger(__name__)

_INDEX_DB_NAME = "code_search.db"
_MAX_INDEX_FILES = 5000
_SKIP_DIRS = IGNORED_DIRS  # includes ``.agentcore`` (index lives under it)


class IndexManager:
    """Builds and queries the workspace BM25 code index.

    File contents are read through ``WorkspaceBackend`` (not direct disk), so the
    same manager works for ``ServerWorkspace`` and channel-backed ``LocalWorkspace``.
    ``index_dir`` holds the SQLite DB; for local disk workspaces this is typically
    ``<workspace>/.agentcore/index``.
    """

    def __init__(self, index_dir: str) -> None:
        self._index_dir = str(Path(index_dir))
        self._bm25: BM25Index | None = None
        self._index_truncated = False
        self._last_ensure_complete = False

    @classmethod
    def for_workspace_root(cls, workspace_root: str) -> IndexManager:
        """Index beside a real workspace root (``.agentcore/index``)."""
        return cls(str(Path(workspace_root) / ".agentcore" / "index"))

    def _get_bm25(self) -> BM25Index:
        if self._bm25 is None:
            db_path = os.path.join(self._index_dir, _INDEX_DB_NAME)
            self._bm25 = BM25Index(db_path)
        return self._bm25

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

        index_stale = self._index_truncated or not self._last_ensure_complete
        return CodeSearchResult(chunks=chunks, scores=scores, index_stale=index_stale)


def _should_skip_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(part in _SKIP_DIRS for part in parts)
