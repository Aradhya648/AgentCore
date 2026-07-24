"""Handoff job (本地→云交接: 云端在快照上跑团队, 双模式工作区 P2e / e2) schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DispatchHandoffRequest(BaseModel):
    """Hand a task off to a cloud team seeded from the local workspace snapshot."""

    task: str


class HandoffJobSummary(BaseModel):
    """One local→云 handoff job: its lifecycle + the snapshots bracketing it.

    ``base_snapshot_id`` is the user's local files the cloud team ran on (the e3
    diff base, under the source conversation's storage key); ``result_snapshot_id``
    is the team's output (under the hidden job conversation's key), NULL until the
    run succeeds. ``job_conversation_id`` hosts the team's replayable graph.
    """

    id: str
    source_conversation_id: str
    job_conversation_id: str
    base_snapshot_id: str
    result_snapshot_id: str | None
    task: str
    status: Literal["pending", "running", "succeeded", "failed"]
    error: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class HandoffJobListResponse(BaseModel):
    data: list[HandoffJobSummary]
    total: int


class HandoffFileChange(BaseModel):
    """One file's base→result delta in a finished handoff (双模式工作区 P2e / e3).

    ``base_sha`` / ``result_sha`` are sha256 hex on each side (null when absent:
    base for an add, result for a delete). ``content`` is the result's UTF-8 text
    for an add/modify (null for a delete, or for a binary result — ``is_binary``
    flags the latter, fetched via snapshot download). The desktop hashes its current
    local copy and three-way-classifies each entry against ``base_sha`` before
    applying (clean / already-applied / conflict).
    """

    path: str
    change_type: Literal["added", "modified", "deleted"]
    base_sha: str | None
    result_sha: str | None
    is_binary: bool
    content: str | None
    size_bytes: int

    model_config = {"from_attributes": True}


class HandoffDiffResponse(BaseModel):
    """A finished handoff's result diff: the change set to apply back to local files.

    ``data`` is the per-file change set (sorted by path); ``added`` / ``modified`` /
    ``deleted`` are counts for the PR-card header.
    """

    job_id: str
    data: list[HandoffFileChange]
    total: int
    added: int
    modified: int
    deleted: int


class HandoffApplySelection(BaseModel):
    """One file's apply decision in a handoff PR review (双模式工作区 P2e / e3).

    ``decision`` is ``cloud`` (take the team's version) or ``local`` (keep the
    user's). ``local_sha`` is the hash the desktop currently sees for the file — the
    third input to the server's authoritative three-way conflict check (null when
    the file is absent locally). ``force`` applies the cloud version even when the
    server judges a conflict (the user's explicit override after seeing it flagged).
    """

    path: str
    decision: Literal["cloud", "local"] = "cloud"
    local_sha: str | None = None
    force: bool = False


class ApplyHandoffRequest(BaseModel):
    """Apply selected result changes from a finished handoff back to local files.

    ``selections`` carries one entry per file the user decided on; files not listed
    are left untouched locally. The apply streams SSE (it drives WRITE_BYTES / DELETE
    ops the bound desktop fulfils) and ends with a ``handoff_apply_done`` event.
    """

    selections: list[HandoffApplySelection]
