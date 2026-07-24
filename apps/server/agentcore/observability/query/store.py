"""Postgres / offline-export conversation stores for log timeline joins."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


def resolve_database_url() -> str:
    """Resolve DB URL: ``AGENTCORE_DATABASE_URL`` → ``DATABASE_URL`` → settings."""
    for key in ("AGENTCORE_DATABASE_URL", "DATABASE_URL"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    from agentcore.config import settings

    return settings.database_url


@runtime_checkable
class ConversationStore(Protocol):
    """Join target for message bodies (Postgres or export dir)."""

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None: ...

    async def get_messages(self, conversation_id: str) -> list[dict[str, Any]]: ...

    async def list_recent(self, n: int = 5) -> list[dict[str, Any]]: ...

    async def aclose(self) -> None: ...


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


class ExportConversationStore:
    """Offline store over ``pnpm sync:logs`` export directory."""

    def __init__(self, export_dir: Path) -> None:
        self.export_dir = export_dir

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        for conv in _read_jsonl(self.export_dir / "conversations.jsonl"):
            if str(conv.get("id")) == conversation_id:
                return {
                    "id": str(conv["id"]),
                    "title": conv.get("title"),
                    "agent_id": conv.get("agent_id"),
                    "created_at": str(conv.get("created_at", "")),
                }
        return None

    async def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        journal_counts: dict[str, int] = {}
        for entry in _read_jsonl(self.export_dir / "turn_journal.jsonl"):
            if str(entry.get("conversation_id")) != conversation_id:
                continue
            turn_id = str(entry.get("turn_id", ""))
            journal_counts[turn_id] = journal_counts.get(turn_id, 0) + 1

        messages: list[dict[str, Any]] = []
        for row in _read_jsonl(self.export_dir / "messages.jsonl"):
            if str(row.get("conversation_id")) != conversation_id:
                continue
            content = row.get("content") or ""
            tool_calls = row.get("tool_calls")
            msg_id = str(row.get("id", ""))
            msg: dict[str, Any] = {
                "type": "message",
                "timestamp": str(row.get("created_at", "")),
                "id": msg_id,
                "role": row.get("role"),
                "content_preview": content[:200],
                "content_len": len(content),
                "has_reasoning": bool(row.get("reasoning_content")),
                "tool_calls_count": len(tool_calls) if tool_calls else 0,
                "runs_count": journal_counts.get(msg_id, 0),
                "finish_reason": row.get("finish_reason"),
                "trace_id": row.get("trace_id"),
            }
            if row.get("usage"):
                msg["usage"] = row["usage"]
            messages.append(msg)
        messages.sort(key=lambda x: x.get("timestamp", ""))
        return messages

    async def list_recent(self, n: int = 5) -> list[dict[str, Any]]:
        rows = sorted(
            _read_jsonl(self.export_dir / "conversations.jsonl"),
            key=lambda c: str(c.get("created_at", "")),
            reverse=True,
        )[:n]
        return [
            {
                "id": str(r.get("id", "")),
                "title": r.get("title"),
                "created_at": str(r.get("created_at", "")),
            }
            for r in rows
        ]

    async def aclose(self) -> None:
        return None


class PostgresConversationStore:
    """Live store over ``messages`` / ``conversations`` / ``turn_journal``."""

    def __init__(self, database_url: str | None = None) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        url = database_url or resolve_database_url()
        self._engine = create_async_engine(url, pool_size=2, max_overflow=0)

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, title, agent_id, created_at "
                        "FROM conversations WHERE id = :cid"
                    ),
                    {"cid": conversation_id},
                )
            ).first()
        if not row:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "agent_id": row[2],
            "created_at": str(row[3]),
        }

    async def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, role, content, reasoning_content, usage, created_at, "
                        "trace_id "
                        "FROM messages WHERE conversation_id = :cid ORDER BY created_at"
                    ),
                    {"cid": conversation_id},
                )
            ).all()
            journal_counts: dict[str, int] = {}
            for jr in (
                await conn.execute(
                    text(
                        "SELECT turn_id, count(*) FROM turn_journal "
                        "WHERE conversation_id = :cid GROUP BY turn_id"
                    ),
                    {"cid": conversation_id},
                )
            ).all():
                journal_counts[jr[0]] = jr[1]

        messages: list[dict[str, Any]] = []
        for r in rows:
            msg: dict[str, Any] = {
                "type": "message",
                "timestamp": str(r[5]),
                "id": r[0],
                "role": r[1],
                "content_preview": (r[2] or "")[:200],
                "content_len": len(r[2] or ""),
                "has_reasoning": bool(r[3]),
                "tool_calls_count": 0,
                "runs_count": journal_counts.get(r[0], 0),
                "finish_reason": None,
                # DB↔log join key (assistant rows carry the turn's trace;
                # user / handoff rows are NULL by design).
                "trace_id": r[6],
            }
            if r[4]:
                msg["usage"] = r[4]
            messages.append(msg)
        return messages

    async def list_recent(self, n: int = 5) -> list[dict[str, Any]]:
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, title, created_at FROM conversations "
                        "WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT :n"
                    ),
                    {"n": n},
                )
            ).all()
        return [
            {"id": r[0], "title": r[1], "created_at": str(r[2])} for r in rows
        ]

    async def aclose(self) -> None:
        await self._engine.dispose()


def open_conversation_store(
    *,
    export_dir: Path | None = None,
    database_url: str | None = None,
) -> ConversationStore:
    """Factory: export dir wins when provided, else Postgres."""
    if export_dir is not None:
        return ExportConversationStore(export_dir)
    return PostgresConversationStore(database_url=database_url)
