"""Discover demo tape JSON files under ``demos/tapes/`` (dev-only)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcore.config.paths import PROJECT_ROOT
from agentcore.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TapeInfo:
    """One tape file ready for one-click replay."""

    id: str
    path: Path
    repo_relative: str
    title: str
    user_prompt: str
    duration_ms: int | None
    event_count: int | None
    turn_count: int = 1


def tapes_dir() -> Path:
    return PROJECT_ROOT / "demos" / "tapes"


def _catalog_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Extract list-row fields from a raw tape document (no full normalize)."""
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    turns = data.get("turns")
    turn_count = 1
    user_prompt = str(meta.get("user_prompt") or "").strip()
    duration = meta.get("duration_ms")
    event_count = meta.get("event_count")

    if isinstance(turns, list) and turns:
        turn_count = len(turns)
        if not user_prompt:
            first = turns[0] if isinstance(turns[0], dict) else {}
            user_prompt = str(first.get("user_prompt") or "").strip()
        if not isinstance(event_count, int):
            total = 0
            for t in turns:
                if isinstance(t, dict) and isinstance(t.get("events"), list):
                    total += len(t["events"])
            event_count = total
        if not isinstance(duration, int):
            total_dur = 0
            for t in turns:
                if not isinstance(t, dict):
                    continue
                evs = t.get("events") or []
                if isinstance(evs, list) and evs:
                    last = evs[-1] if isinstance(evs[-1], dict) else {}
                    total_dur += int(last.get("t_ms") or 0)
            duration = total_dur
    elif isinstance(meta.get("turn_count"), int) and meta["turn_count"] > 0:
        turn_count = int(meta["turn_count"])

    return {
        "title": str(meta.get("title") or "").strip(),
        "user_prompt": user_prompt,
        "duration_ms": int(duration) if isinstance(duration, int) else None,
        "event_count": int(event_count) if isinstance(event_count, int) else None,
        "turn_count": turn_count,
    }


def _read_tape_summary(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("demo_tape.catalog_read_failed", path=str(path), error=str(e))
        return {}
    if not isinstance(data, dict):
        return {}
    return _catalog_fields(data)


def list_tapes() -> list[TapeInfo]:
    """List ``*.json`` tapes under ``demos/tapes/``, sorted by id."""
    root = tapes_dir()
    if not root.is_dir():
        return []
    out: list[TapeInfo] = []
    for path in sorted(root.glob("*.json")):
        if not path.is_file():
            continue
        fields = _read_tape_summary(path)
        tape_id = path.stem
        title = fields.get("title") or tape_id
        title = str(title).strip() or tape_id
        try:
            rel = path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            rel = f"demos/tapes/{path.name}"
        out.append(
            TapeInfo(
                id=tape_id,
                path=path,
                repo_relative=rel,
                title=title,
                user_prompt=str(fields.get("user_prompt") or ""),
                duration_ms=fields.get("duration_ms"),
                event_count=fields.get("event_count"),
                turn_count=int(fields.get("turn_count") or 1),
            )
        )
    return out


def resolve_tape(tape_id: str) -> TapeInfo | None:
    """Resolve a tape by stem id (e.g. ``lv-molihua-trademark``)."""
    needle = (tape_id or "").strip()
    if not needle or "/" in needle or "\\" in needle or ".." in needle:
        return None
    for info in list_tapes():
        if info.id == needle:
            return info
    return None
