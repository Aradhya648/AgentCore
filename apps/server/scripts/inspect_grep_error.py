"""Read-only: dump the grep tool calls (arguments + result/error) from a turn's
persisted journal, to root-cause a ``tool=grep status=error`` seen in the logs.

The CEO's own finalize tools are journaled (tool_use_start/tool_use_end are in
``_JOURNAL_EVENT_TYPES``), and a delegated turn persists the full journal — so the
exact pattern/path the model passed and the error string grep returned are all
recoverable from Postgres. No LLM, no writes.

Run from ``apps/server``::

    uv run python scripts/inspect_grep_error.py <conversation_id>
"""

from __future__ import annotations

import asyncio
import json
import sys

from agentcore.db import async_session_factory
from agentcore.db.repositories import MessageRepository, TurnJournalRepository


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: inspect_grep_error.py <conversation_id>")
    conv_id = sys.argv[1]

    async with async_session_factory() as session:
        messages = await MessageRepository(session).list_recent(conv_id, limit=20)
        assistants = [m for m in messages if m.role == "assistant"]
        if not assistants:
            raise SystemExit(f"no assistant message in conversation {conv_id}")
        # list_recent is newest-first; take the latest assistant turn.
        msg = assistants[0]
        print(f"[message] assistant turn id={msg.id}")
        entries = await TurnJournalRepository(session).load(msg.id)

    print(f"[journal] {len(entries)} entries\n")

    # Pair tool_use_start (carries tool_name + arguments) with its tool_use_end
    # (carries status + result/error) by tool_call_id.
    starts: dict[str, dict] = {}
    grep_calls: list[tuple[dict, dict | None]] = []
    for e in entries:
        kind = e.get("kind") or e.get("type")
        payload = e.get("payload") or {}
        if kind == "tool_use_start":
            starts[payload.get("tool_call_id", "")] = payload
        elif kind == "tool_use_end":
            cid = payload.get("tool_call_id", "")
            start = starts.get(cid)
            if start and start.get("tool_name") == "grep":
                grep_calls.append((start, payload))

    if not grep_calls:
        print("No grep tool calls found in this turn's journal.")
        # Show what tools WERE called, to confirm we're looking at the right turn.
        names = [
            (e.get("payload") or {}).get("tool_name")
            for e in entries
            if (e.get("kind") or e.get("type")) == "tool_use_start"
        ]
        print("tools called:", [n for n in names if n])
        return

    for i, (start, end) in enumerate(grep_calls, 1):
        print(f"==== grep call #{i} ====")
        print("arguments:", json.dumps(start.get("arguments"), ensure_ascii=False))
        if end is None:
            print("(no matching tool_use_end)")
            continue
        print("status:   ", end.get("status"))
        result = end.get("result")
        if isinstance(result, str):
            print("result:   ", result[:1000])
        else:
            print("result:   ", json.dumps(result, ensure_ascii=False)[:1000])
        print()


if __name__ == "__main__":
    asyncio.run(main())
