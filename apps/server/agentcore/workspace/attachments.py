"""Persist user attachments into the conversation's workspace (附件驻留 / 引用即驻留).

Upgrades an @-mention / paperclip attachment from one-shot prompt context into a
durable project-space file under ``attachments/``. Text attachments may still be
written here from the client-extracted body; binary attachments are expected to
arrive already resident (``workspace_path`` set by the desktop main-process copy)
with ``binary=True`` and empty ``text``.

Text-like binaries (docx/pdf/pptx/txt …) are **pre-parsed** after residency
(``attachment_parse``): a readable ``*.md`` copy is written beside the original
when extraction succeeds. Spreadsheets (xlsx/csv) are left untouched for runtime
``code_execute``. Parse failures never break the turn — path-hint fallback remains.

Directory attachments carry only a listing (no file bodies), so nothing is
written for them. Conversation references likewise pass through untouched.

This is intentionally a thin service over ``WorkspaceBackend`` (it never touches
``Path``), so the same residency works for ``LocalWorkspace``.
"""

from __future__ import annotations

import os

from agentcore.core.logging import get_logger
from agentcore.workspace.attachment_parse import ParseStatus, preparse_resident, should_preparse
from agentcore.workspace.protocol import WorkspaceBackend, WorkspaceError

logger = get_logger(__name__)

# Subdirectory that holds resident user attachments inside every workspace.
ATTACHMENTS_DIR = "attachments"


def _safe_attachment_name(name: str) -> str:
    """Reduce a user-supplied name to a single safe filename component.

    Strips any directory parts (``/`` and ``\\``) so an attachment can only land
    directly inside ``attachments/`` — the backend's traversal guard is the hard
    boundary, this just keeps names tidy and predictable. Falls back to a generic
    name when nothing usable remains.
    """
    base = os.path.basename((name or "").replace("\\", "/").strip())
    base = base.strip().strip(".")
    return base or "attachment"


def _dedup(name: str, used: set[str]) -> str:
    """Disambiguate ``name`` against ``used`` by inserting ``" (n)"`` before ext.

    Two attachments in one turn can share a filename; without this the second
    ``write`` would clobber the first. Across turns the same name maps back to
    the same path on purpose (the latest copy wins — history lives in snapshots).
    """
    if name not in used:
        used.add(name)
        return name
    root, ext = os.path.splitext(name)
    i = 2
    candidate = f"{root} ({i}){ext}"
    while candidate in used:
        i += 1
        candidate = f"{root} ({i}){ext}"
    used.add(candidate)
    return candidate


def _normalize_client_workspace_path(raw: str | None) -> str | None:
    """Accept only a single-segment path under ``attachments/`` from the client."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.replace("\\", "/").strip().lstrip("/")
    if not cleaned.startswith(f"{ATTACHMENTS_DIR}/"):
        return None
    rest = cleaned[len(ATTACHMENTS_DIR) + 1 :]
    if not rest or "/" in rest or ".." in rest:
        return None
    return f"{ATTACHMENTS_DIR}/{_safe_attachment_name(rest)}"


async def _enrich_with_preparse(
    backend: WorkspaceBackend, item: dict, *, workspace_path: str
) -> None:
    """Attempt分流预解析 for a binary resident; mutate ``item`` in place on success."""
    if not should_preparse(item.get("name"), workspace_path):
        item["parse_status"] = ParseStatus.SKIPPED.value
        return

    result = await preparse_resident(
        backend, workspace_path=workspace_path, name=item.get("name")
    )
    item["parse_status"] = result.status.value
    if result.parsed_workspace_path:
        item["parsed_workspace_path"] = result.parsed_workspace_path
    if result.status == ParseStatus.OK and result.text:
        item["text"] = result.text
    elif result.status == ParseStatus.SCANNED and result.text:
        # Surface the scan notice as the attachment body so prompt assembly sees it.
        item["text"] = result.text
    # FAILED / SKIPPED: leave text empty → prompt falls back to binary path hint.


async def persist_attachments(
    backend: WorkspaceBackend, attachments: list[dict] | None
) -> list[dict]:
    """Write file attachments into the workspace; return them enriched in order.

    Each returned dict is the input dict plus a ``workspace_path`` key for every
    file actually written or client-pre-resident (``attachments/<name>``). Only
    ``kind="file"`` is persisted; directory listings, conversation references and
    empty-text non-binary files are passed through untouched. A per-file write
    failure is logged and skipped — a bad attachment must never break the turn.

    Binary residents in the text-document bucket may also gain ``text``,
    ``parsed_workspace_path``, and ``parse_status`` from pre-parse.
    """
    if not attachments:
        return []

    used: set[str] = set()
    enriched: list[dict] = []
    for att in attachments:
        item = dict(att)
        kind = att.get("kind") or "file"
        text = att.get("text") or ""
        binary = bool(att.get("binary"))
        pre = _normalize_client_workspace_path(att.get("workspace_path"))

        if kind == "file" and pre:
            # 引用即驻留：桌面（或云端 PUT）已写入字节；登记路径，勿用 truncated text 覆盖。
            used.add(os.path.basename(pre))
            item["workspace_path"] = pre
            item["binary"] = binary
            if binary:
                await _enrich_with_preparse(backend, item, workspace_path=pre)
        elif kind == "file" and text.strip() and not binary:
            item.pop("workspace_path", None)
            rel = f"{ATTACHMENTS_DIR}/{_dedup(_safe_attachment_name(att.get('name') or ''), used)}"
            try:
                await backend.write(rel, text)
                item["workspace_path"] = rel
            except WorkspaceError as e:
                logger.warning(
                    "attachment.persist_failed",
                    name=att.get("name"),
                    error=str(e),
                )
        else:
            # 无效 / 缺失的 client workspace_path 不得透传到 enriched 结果。
            if not pre:
                item.pop("workspace_path", None)
            if kind == "file" and binary and not pre:
                logger.warning(
                    "attachment.binary_missing_workspace_path",
                    name=att.get("name"),
                )
        enriched.append(item)
    return enriched


def to_stored_metadata(attachments: list[dict]) -> list[dict]:
    """Project enriched attachments to the columns persisted on the message.

    Drops the one-shot ``text`` (never stored) and keeps display metadata plus
    the durable ``workspace_path`` so the client can render and download it.
    Pre-parse copies live on disk under ``*.md``; they are not persisted as
    message columns (agents find them via workspace path / file tools).
    """
    return [
        {
            "name": a.get("name"),
            "path": a.get("path"),
            "truncated": bool(a.get("truncated")),
            "kind": a.get("kind") or "file",
            "workspace_path": a.get("workspace_path"),
            "conversation_id": a.get("conversation_id"),
            "binary": bool(a.get("binary")),
        }
        for a in attachments
    ]


def interjection_attachment_meta(attachments: list[dict]) -> list[dict]:
    """Project enriched attachments for SSE / coordination briefs (no inline text).

    Carries display name, durable ``workspace_path`` when present, and the binary
    flag so the CEO brief and team-block chips can surface path-only references.
    """
    out: list[dict] = []
    for a in attachments:
        name = a.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        leaf: dict = {"name": name, "binary": bool(a.get("binary"))}
        wp = a.get("workspace_path")
        if isinstance(wp, str) and wp.strip():
            leaf["workspace_path"] = wp
        out.append(leaf)
    return out

