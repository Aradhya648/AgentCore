"""Export conversation data from Postgres to JSONL files for offline analysis.

Run from apps/server:

    uv run python scripts/export_conversations.py [--days N] [--output DIR]

Default: last 7 days → ../../data/export (repo-root data/export/).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

# scripts/ -> server -> apps -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "export"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _row_to_dict(columns: list[str], row: Any) -> dict[str, Any]:
    return {col: row[i] for i, col in enumerate(columns)}


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> int:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
    return len(rows)


def _create_engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    from agentcore.config import settings

    return create_async_engine(settings.database_url, pool_size=2, max_overflow=0)


_CONVERSATIONS_SQL = """
SELECT id, user_id, title, agent_id, mode, folder_id,
       pinned, archived, created_at
FROM conversations
WHERE deleted_at IS NULL AND created_at >= :cutoff
"""

_MESSAGES_SQL = """
SELECT id, conversation_id, role, content, reasoning_content,
       tool_calls, usage, attachments, citations, followups,
       feedback, finish_reason, trace_id, created_at
FROM messages
WHERE conversation_id = ANY(:conv_ids)
ORDER BY conversation_id, created_at
"""

_COST_EVENTS_SQL = """
SELECT id, user_id, conversation_id, message_id, run_id,
       parent_run_id, agent_id, role, model, tokens, cost,
       cost_total_nano, currency, rounds, duration_ms, trace_id, created_at
FROM cost_events
WHERE conversation_id = ANY(:conv_ids)
"""

_TURN_METRICS_SQL = """
SELECT id, turn_id, conversation_id, user_id, agent_id, trace_id,
       kind, status, finish_reason, error, rounds, duration_ms,
       delegated, workers, input_tokens, output_tokens,
       boundary_yields, scope_signals, revises, escalations, created_at
FROM turn_metrics
WHERE conversation_id = ANY(:conv_ids)
"""

_TURN_JOURNAL_SQL = """
SELECT turn_id, seq, kind, payload, ts, conversation_id,
       trace_id, created_at
FROM turn_journal
WHERE conversation_id = ANY(:conv_ids)
ORDER BY turn_id, seq
"""


async def export_conversations(days: int, output_dir: Path) -> None:
    from sqlalchemy import text

    output_dir.mkdir(parents=True, exist_ok=True)
    engine = _create_engine()
    cutoff = datetime.now(UTC) - timedelta(days=days)

    async with engine.connect() as conn:
        conv_rows = (
            await conn.execute(
                text(_CONVERSATIONS_SQL),
                {"cutoff": cutoff},
            )
        ).all()
        conv_cols = [
            "id",
            "user_id",
            "title",
            "agent_id",
            "mode",
            "folder_id",
            "pinned",
            "archived",
            "created_at",
        ]
        conversations = [_row_to_dict(conv_cols, r) for r in conv_rows]
        conv_ids = [c["id"] for c in conversations]

        conv_count = _write_jsonl(output_dir / "conversations.jsonl", conversations)

        if not conv_ids:
            for name in (
                "messages",
                "cost_events",
                "turn_metrics",
                "turn_journal",
            ):
                _write_jsonl(output_dir / f"{name}.jsonl", [])
        else:
            msg_rows = (
                await conn.execute(text(_MESSAGES_SQL), {"conv_ids": conv_ids})
            ).all()
            msg_cols = [
                "id",
                "conversation_id",
                "role",
                "content",
                "reasoning_content",
                "tool_calls",
                "usage",
                "attachments",
                "citations",
                "followups",
                "feedback",
                "finish_reason",
                "trace_id",
                "created_at",
            ]
            msg_count = _write_jsonl(
                output_dir / "messages.jsonl",
                [_row_to_dict(msg_cols, r) for r in msg_rows],
            )

            cost_rows = (
                await conn.execute(text(_COST_EVENTS_SQL), {"conv_ids": conv_ids})
            ).all()
            cost_cols = [
                "id",
                "user_id",
                "conversation_id",
                "message_id",
                "run_id",
                "parent_run_id",
                "agent_id",
                "role",
                "model",
                "tokens",
                "cost",
                "cost_total_nano",
                "currency",
                "rounds",
                "duration_ms",
                "trace_id",
                "created_at",
            ]
            cost_count = _write_jsonl(
                output_dir / "cost_events.jsonl",
                [_row_to_dict(cost_cols, r) for r in cost_rows],
            )

            tm_rows = (
                await conn.execute(text(_TURN_METRICS_SQL), {"conv_ids": conv_ids})
            ).all()
            tm_cols = [
                "id",
                "turn_id",
                "conversation_id",
                "user_id",
                "agent_id",
                "trace_id",
                "kind",
                "status",
                "finish_reason",
                "error",
                "rounds",
                "duration_ms",
                "delegated",
                "workers",
                "input_tokens",
                "output_tokens",
                "boundary_yields",
                "scope_signals",
                "revises",
                "escalations",
                "created_at",
            ]
            tm_count = _write_jsonl(
                output_dir / "turn_metrics.jsonl",
                [_row_to_dict(tm_cols, r) for r in tm_rows],
            )

            tj_rows = (
                await conn.execute(text(_TURN_JOURNAL_SQL), {"conv_ids": conv_ids})
            ).all()
            tj_cols = [
                "turn_id",
                "seq",
                "kind",
                "payload",
                "ts",
                "conversation_id",
                "trace_id",
                "created_at",
            ]
            tj_count = _write_jsonl(
                output_dir / "turn_journal.jsonl",
                [_row_to_dict(tj_cols, r) for r in tj_rows],
            )

    await engine.dispose()

    stats = [
        ("conversations.jsonl", conv_count),
    ]
    if conv_ids:
        stats.extend(
            [
                ("messages.jsonl", msg_count),
                ("cost_events.jsonl", cost_count),
                ("turn_metrics.jsonl", tm_count),
                ("turn_journal.jsonl", tj_count),
            ]
        )
    else:
        for name in ("messages", "cost_events", "turn_metrics", "turn_journal"):
            stats.append((f"{name}.jsonl", 0))

    print(f"\nExport complete → {output_dir}\n")
    total_bytes = 0
    for filename, count in stats:
        path = output_dir / filename
        size = path.stat().st_size if path.exists() else 0
        total_bytes += size
        print(f"  {filename:<24} {count:>6} rows  {size:>10,} bytes")
    print(f"\n  {'total':<24} {'':>6}      {total_bytes:>10,} bytes\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Export conversations from last N days")
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Output directory (default: {_DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    asyncio.run(export_conversations(args.days, args.output.resolve()))


if __name__ == "__main__":
    main()
