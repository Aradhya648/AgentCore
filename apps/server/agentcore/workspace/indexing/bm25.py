"""BM25 full-text index backed by SQLite FTS5."""

from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
import time
from pathlib import Path

from agentcore.workspace.indexing.chunker import RawChunk

_FTS_TOKEN = re.compile(r"\w+", re.UNICODE)


class BM25Index:
    """SQLite FTS5 index for code chunks."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
                    path UNINDEXED,
                    symbol,
                    symbol_type,
                    language UNINDEXED,
                    content,
                    start_line UNINDEXED,
                    end_line UNINDEXED,
                    tokenize='unicode61'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_hashes (
                    path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    indexed_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def get_file_hash(self, path: str) -> str | None:
        return await asyncio.to_thread(self._get_file_hash_sync, path)

    def _get_file_hash_sync(self, path: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_hash FROM file_hashes WHERE path = ?", (path,)
            ).fetchone()
        return str(row["content_hash"]) if row else None

    async def list_indexed_paths(self) -> set[str]:
        return await asyncio.to_thread(self._list_indexed_paths_sync)

    def _list_indexed_paths_sync(self) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT path FROM file_hashes").fetchall()
        return {str(r["path"]) for r in rows}

    async def upsert_file(self, path: str, content: str, chunks: list[RawChunk]) -> None:
        await asyncio.to_thread(self._upsert_file_sync, path, content, chunks)

    def _upsert_file_sync(self, path: str, content: str, chunks: list[RawChunk]) -> None:
        digest = self.content_hash(content)
        now = time.time()
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO chunks(
                        path, symbol, symbol_type, language, content, start_line, end_line
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.path,
                        chunk.symbol or "",
                        chunk.symbol_type or "",
                        chunk.language,
                        chunk.content,
                        chunk.start_line,
                        chunk.end_line,
                    ),
                )
            conn.execute(
                """
                INSERT INTO file_hashes(path, content_hash, indexed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    indexed_at = excluded.indexed_at
                """,
                (path, digest, now),
            )
            conn.commit()

    async def remove_file(self, path: str) -> None:
        await asyncio.to_thread(self._remove_file_sync, path)

    def _remove_file_sync(self, path: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
            conn.execute("DELETE FROM file_hashes WHERE path = ?", (path,))
            conn.commit()

    async def search(
        self,
        query: str,
        *,
        language: str | None = None,
        path_prefix: str = ".",
        limit: int = 10,
    ) -> list[tuple[RawChunk, float]]:
        return await asyncio.to_thread(
            self._search_sync,
            query,
            language,
            path_prefix,
            limit,
        )

    def _search_sync(
        self,
        query: str,
        language: str | None,
        path_prefix: str,
        limit: int,
    ) -> list[tuple[RawChunk, float]]:
        fts_query = _to_fts_query(query)
        if not fts_query:
            return []

        prefix = _normalize_prefix(path_prefix)
        params: list[object] = [fts_query]
        filters = ["chunks MATCH ?"]

        if language:
            filters.append("language = ?")
            params.append(language)

        if prefix:
            filters.append("path LIKE ? ESCAPE '\\'")
            params.append(f"{_escape_like(prefix)}%")

        where = " AND ".join(filters)
        sql = f"""
            SELECT path, symbol, symbol_type, language, content, start_line, end_line,
                   bm25(chunks) AS rank
            FROM chunks
            WHERE {where}
            ORDER BY rank
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as conn:
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []

        if not rows:
            return []

        raw_scores = [-float(r["rank"]) for r in rows]
        max_score = max(raw_scores) or 1.0
        results: list[tuple[RawChunk, float]] = []
        for row, raw in zip(rows, raw_scores, strict=True):
            chunk = RawChunk(
                path=str(row["path"]),
                symbol=str(row["symbol"]) or None,
                symbol_type=str(row["symbol_type"]) or None,
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                language=str(row["language"]),
                content=str(row["content"]),
            )
            score = max(0.0, min(1.0, raw / max_score))
            results.append((chunk, score))
        return results


def _to_fts_query(query: str) -> str | None:
    tokens = _FTS_TOKEN.findall(query)
    if not tokens:
        return None
    # OR across tokens for better recall on natural-language queries.
    return " OR ".join(f'"{t}"' for t in tokens)


def _normalize_prefix(path_prefix: str) -> str:
    p = path_prefix.strip().replace("\\", "/")
    if not p or p == ".":
        return ""
    return p.strip("/")


def _escape_like(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
