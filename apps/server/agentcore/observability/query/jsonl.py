"""JSONL log reader: rotation merge + synthetic-traffic filter."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from agentcore.observability.query.timeutil import parse_timestamp


@runtime_checkable
class LogEventSource(Protocol):
    """Readable stream of product-AI log event dicts."""

    def iter_raw(self) -> Iterator[dict[str, Any] | None]:
        """Yield parsed objects; ``None`` means a bad JSON line."""

    def discover_files(self) -> list[Path]: ...


@dataclass(frozen=True, slots=True)
class ReadFilter:
    """Common filters applied while reading JSONL."""

    since: datetime | None = None
    include_synthetic: bool = False
    field_equals: tuple[str, str] | None = None  # (field, value)


@dataclass
class ReadStats:
    """Counters collected while iterating."""

    total_kept: int = 0
    bad_lines: int = 0
    excluded_synthetic: int = 0
    synthetic_by_kind: dict[str, int] = field(default_factory=dict)
    files: list[Path] = field(default_factory=list)


def discover_log_files(primary: Path) -> list[Path]:
    """Primary file plus RotatingFileHandler backups, oldest → newest.

    ``name.jsonl.N`` (higher N = older) then ``name.jsonl`` (current).
    """
    primary = primary.resolve()
    parent = primary.parent
    name = primary.name
    backups: list[tuple[int, Path]] = []
    for p in parent.glob(name + ".*"):
        suffix = p.name[len(name) + 1 :]
        if suffix.isdigit():
            backups.append((int(suffix), p))
    backups.sort(key=lambda t: t[0], reverse=True)
    files = [p for _, p in backups]
    if primary.exists():
        files.append(primary)
    return files


def is_synthetic(obj: dict[str, Any]) -> bool:
    """True when the line carries ``traffic=eval|test`` (or any traffic tag)."""
    return obj.get("traffic") is not None


class JsonlLogSource:
    """Read a primary JSONL path plus rotating backups."""

    def __init__(self, primary: Path) -> None:
        self.primary = primary

    def discover_files(self) -> list[Path]:
        return discover_log_files(self.primary)

    def iter_raw(self) -> Iterator[dict[str, Any] | None]:
        for path in self.discover_files():
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            yield None
            except OSError:
                continue


def iter_events(
    source: LogEventSource,
    filt: ReadFilter | None = None,
    *,
    stats: ReadStats | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield kept events after since / synthetic / field filters."""
    filt = filt or ReadFilter()
    out_stats = stats if stats is not None else ReadStats()
    out_stats.files = source.discover_files()

    for obj in source.iter_raw():
        if obj is None:
            out_stats.bad_lines += 1
            continue
        if filt.since is not None:
            ts = parse_timestamp(obj.get("timestamp"))
            if ts is None or ts < filt.since:
                continue
        if is_synthetic(obj) and not filt.include_synthetic:
            out_stats.excluded_synthetic += 1
            kind = str(obj.get("traffic"))
            out_stats.synthetic_by_kind[kind] = out_stats.synthetic_by_kind.get(kind, 0) + 1
            continue
        if filt.field_equals is not None:
            field_name, value = filt.field_equals
            if obj.get(field_name) != value:
                continue
        out_stats.total_kept += 1
        yield obj


def load_events(
    primary: Path,
    filt: ReadFilter | None = None,
) -> tuple[list[dict[str, Any]], ReadStats]:
    """Load filtered events from ``primary`` (+ backups) into a list."""
    stats = ReadStats()
    events = list(iter_events(JsonlLogSource(primary), filt, stats=stats))
    return events, stats
