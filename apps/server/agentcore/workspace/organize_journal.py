"""Session-scoped organize execution journal for one-shot undo.

Successful move / mkdir from a plan-bound ``file_batch`` are recorded in order.
Undo reverse-plays move (swap src/dst) and mkdir (delete empty dir only);
delete entries are listed for the user (recycle-bin restore) but not auto-undone.
Single-use per conversation session.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Literal

JournalOp = Literal["move", "mkdir", "delete"]

_lock = threading.Lock()
_journals: dict[str, OrganizeJournal] = {}


@dataclass
class JournalEntry:
    op: JournalOp
    """For move: source was moved to destination (undo = move dest→source)."""
    source: str = ""
    destination: str = ""
    """For mkdir / delete: the path touched."""
    path: str = ""


@dataclass
class OrganizeJournal:
    conversation_id: str
    plan_id: str
    entries: list[JournalEntry] = field(default_factory=list)
    undone: bool = False


def record_batch(
    *,
    conversation_id: str,
    plan_id: str,
    successes: list[dict[str, Any]],
) -> OrganizeJournal:
    """Append successful organize ops (replaces prior journal for this conversation)."""
    entries: list[JournalEntry] = []
    for item in successes:
        op = str(item.get("op", "")).strip()
        if op == "move":
            entries.append(
                JournalEntry(
                    op="move",
                    source=str(item.get("source", "")).strip(),
                    destination=str(item.get("destination", "")).strip(),
                )
            )
        elif op == "mkdir":
            entries.append(
                JournalEntry(op="mkdir", path=str(item.get("path", "")).strip())
            )
        elif op == "delete":
            entries.append(
                JournalEntry(op="delete", path=str(item.get("path", "")).strip())
            )
    journal = OrganizeJournal(
        conversation_id=conversation_id,
        plan_id=plan_id,
        entries=entries,
        undone=False,
    )
    with _lock:
        _journals[conversation_id] = journal
    return journal


def get_journal(conversation_id: str) -> OrganizeJournal | None:
    with _lock:
        return _journals.get(conversation_id)


def mark_undone(conversation_id: str) -> bool:
    with _lock:
        j = _journals.get(conversation_id)
        if j is None or j.undone:
            return False
        j.undone = True
        return True


def build_undo_operations(journal: OrganizeJournal) -> tuple[list[dict[str, Any]], list[str]]:
    """Reverse-play move/mkdir; return (ops, delete_paths_for_user_notice)."""
    undo_ops: list[dict[str, Any]] = []
    deletes: list[str] = []
    for entry in reversed(journal.entries):
        if entry.op == "move" and entry.source and entry.destination:
            undo_ops.append(
                {
                    "op": "move",
                    "source": entry.destination,
                    "destination": entry.source,
                }
            )
        elif entry.op == "mkdir" and entry.path:
            # Best-effort: delete the directory (skip if non-empty at execute time).
            undo_ops.append({"op": "delete", "path": entry.path, "permanent": False})
        elif entry.op == "delete" and entry.path:
            deletes.append(entry.path)
    return undo_ops, deletes


def clear_conversation(conversation_id: str) -> None:
    with _lock:
        _journals.pop(conversation_id, None)


def clear_all_for_tests() -> None:
    with _lock:
        _journals.clear()
