"""Handoff result apply — write the chosen cloud changes back to local files (e3).

The final stage of a local→云 handoff (双模式工作区 P2e / e3): after the user reviews
the diff (``handoff_diff``), the desktop submits a per-file decision (take the cloud
version, or keep local) plus the hash it currently sees locally. This module replays
the accepted changes onto the user's machine over the same ``WorkspaceChannel`` the
engine uses (WRITE_BYTES for an add/modify, DELETE for a removal) — the server never
touches a local ``Path``.

The conflict gate is **server-authoritative**: the base/result hashes come from the
snapshots (not the client), and :func:`~agentcore.workspace.handoff_diff.classify_three_way`
decides per file. A file the user marked "take cloud" that has diverged locally since
the base is refused (status ``conflict``) and left untouched unless the request
explicitly ``force``\\s it — so a stale or careless client can never silently clobber
local edits. Result bytes are written verbatim from the result snapshot (binary
included), so an applied file ends byte-identical to the cloud result and a re-apply
is detected as already-applied (idempotent).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from agentcore.core.logging import get_logger
from agentcore.storage import build_storage_provider
from agentcore.workspace.handoff_diff import (
    ChangeType,
    classify_three_way,
    diff_archives,
    read_archive_entries,
)
from agentcore.workspace.locate import workspace_storage_key
from agentcore.workspace.protocol import WorkspaceBackend, WorkspaceError

logger = get_logger(__name__)

ApplyStatus = Literal["applied", "skipped", "conflict", "error"]


@dataclass(frozen=True)
class ApplySelection:
    """One file's apply decision from the desktop (双模式工作区 P2e / e3).

    ``decision`` is ``cloud`` (take the team's version) or ``local`` (keep the
    user's). ``local_sha`` is the hash the desktop currently sees for the file (the
    third input to the server's three-way classification; ``None`` when the file is
    absent locally). ``force`` applies the cloud version even when the server judges
    a conflict — the user's explicit override after seeing it flagged.
    """

    path: str
    decision: Literal["cloud", "local"] = "cloud"
    local_sha: str | None = None
    force: bool = False


@dataclass(frozen=True)
class ApplyOutcome:
    """What happened to one file in an apply pass (for the PR card + the SSE done event)."""

    path: str
    status: ApplyStatus
    change_type: ChangeType | None
    detail: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "status": self.status,
            "change_type": self.change_type,
            "detail": self.detail,
        }


async def apply_handoff(
    *,
    backend: WorkspaceBackend,
    user_id: str,
    source_folder_id: str | None,
    source_conversation_id: str,
    base_snapshot_id: str,
    job_conversation_id: str,
    result_snapshot_id: str,
    selections: Sequence[ApplySelection],
) -> list[ApplyOutcome]:
    """Apply the selected result changes onto the local workspace ``backend`` (e3).

    Reads the authoritative base + result snapshots (base under the *source* key,
    result under the *job* key — same derivation as the diff), then for each
    selection: a ``local`` decision is skipped; a ``cloud`` decision is classified
    three-way against the snapshot hashes + the client's ``local_sha`` and either
    skipped (already applied), applied (clean, or a forced conflict), or refused
    (``conflict``). Writes go through ``backend`` (so the desktop fulfils them over
    the channel); a per-file write failure is captured as ``error`` and never aborts
    the rest. Returns one outcome per selection, in request order.

    Raises ``SnapshotNotFound`` if either snapshot id is missing (the route maps it
    to 404) — that is a precondition failure, distinct from a per-file write error.
    """
    provider = build_storage_provider()
    base_key = workspace_storage_key(
        user_id=user_id,
        folder_id=source_folder_id,
        conversation_id=source_conversation_id,
    )
    job_key = workspace_storage_key(
        user_id=user_id, folder_id=None, conversation_id=job_conversation_id
    )
    base_archive = await provider.read_snapshot(base_key, base_snapshot_id)
    result_archive = await provider.read_snapshot(job_key, result_snapshot_id)

    changes = {c.path: c for c in diff_archives(base_archive, result_archive)}
    result_entries = read_archive_entries(result_archive)

    outcomes: list[ApplyOutcome] = []
    for sel in selections:
        change = changes.get(sel.path)
        if change is None:
            # Not a real change in this result — refuse to write an arbitrary path.
            outcomes.append(
                ApplyOutcome(sel.path, "error", None, "not a changed path in this result")
            )
            continue

        if sel.decision == "local":
            outcomes.append(
                ApplyOutcome(sel.path, "skipped", change.change_type, "kept local version")
            )
            continue

        verdict = classify_three_way(
            base_sha=change.base_sha,
            result_sha=change.result_sha,
            local_sha=sel.local_sha,
        )
        if verdict == "applied":
            outcomes.append(
                ApplyOutcome(
                    sel.path, "skipped", change.change_type, "local already matches result"
                )
            )
            continue
        if verdict == "conflict" and not sel.force:
            outcomes.append(
                ApplyOutcome(
                    sel.path,
                    "conflict",
                    change.change_type,
                    "local diverged from base since the run; resolve or force",
                )
            )
            continue

        try:
            if change.change_type == "deleted":
                await backend.delete(sel.path)
            else:
                await backend.write_bytes(sel.path, result_entries.get(sel.path, b""))
        except WorkspaceError as e:
            logger.warning(
                "handoff.apply_file_failed",
                source_conversation_id=source_conversation_id,
                path=sel.path,
                error=str(e),
            )
            outcomes.append(
                ApplyOutcome(sel.path, "error", change.change_type, f"{type(e).__name__}: {e}")
            )
            continue

        detail = "applied cleanly" if verdict == "clean" else "applied over conflict (forced)"
        outcomes.append(ApplyOutcome(sel.path, "applied", change.change_type, detail))

    return outcomes
