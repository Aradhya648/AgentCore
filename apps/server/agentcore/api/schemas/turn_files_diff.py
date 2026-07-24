"""A1+ turn files diff API schemas (read-only before/after)."""

from typing import Literal

from pydantic import BaseModel


class TurnFileChange(BaseModel):
    """One path's baseline→live delta for a turn (reuse handoff change shape + base text)."""

    path: str
    change_type: Literal["added", "modified", "deleted"]
    base_sha: str | None
    result_sha: str | None
    is_binary: bool
    content: str | None
    size_bytes: int
    """Result-side UTF-8 when available (same as handoff)."""
    base_content: str | None = None
    """Baseline-side UTF-8 when available (for lineDiff); null for adds / binary."""


class TurnFilesDiffResponse(BaseModel):
    """Read-only turn file diff. ``available=False`` → client falls back to tool-arg previews."""

    message_id: str
    baseline_snapshot_id: str | None
    available: bool
    data: list[TurnFileChange]
    total: int
    added: int
    modified: int
    deleted: int
