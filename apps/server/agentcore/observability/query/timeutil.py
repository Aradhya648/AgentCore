"""Shared time parsing for log query CLIs."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta


def parse_since(spec: str, *, now: datetime | None = None) -> datetime:
    """Parse ``24h`` / ``7d`` / ``2w`` / ISO date-or-datetime into aware UTC cutoff."""
    now = now or datetime.now(UTC)
    s = spec.strip()
    m = re.fullmatch(r"(\d+)\s*([hdw])", s, re.I)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n)}[unit]
        return now - delta
    raw = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as e:
        raise ValueError(
            f"Invalid --since {spec!r}: use 24h / 7d / 2w or an ISO date (YYYY-MM-DD[THH:MM…])"
        ) from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_timestamp(raw: object) -> datetime | None:
    """Parse a JSONL ``timestamp`` field into aware UTC, or None if unusable."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
