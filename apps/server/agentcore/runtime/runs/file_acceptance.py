"""Path-level delivery acceptance for files_touched (验收态 · 块 1 / 块 2).

At run wrap-up each landed path gets ``accepted`` or ``rejected`` (+ reason).
``delivery_status.delivered_files`` / CEO「已交付」only count ``accepted``.
Cite-tier / contract failures that name a path reject that path even when the
run soft-COMPLETEDs — so soft-COMPLETED must not smuggle those paths into the
delivered list.

调研两阶段（``citation_mode=two_phase``）：阶段 A 草案仅内部态，不写入本表；
阶段 B 过闸 → ``accepted``；不过 → ``rejected(citations_unverified)``。draft 永不
出现在 ``delivery_status.artifacts`` 主清单。
"""

from __future__ import annotations

import re
from typing import Any

from agentcore.runtime.runs.types import RunPhase

REASON_CITATIONS_UNVERIFIED = "citations_unverified"
REASON_CONTRACT_FAILED = "contract_failed"
REASON_RUN_FAILED = "run_failed"

# Citation / bibliography failures from ``_artifact_citation_failures``.
_CITE_PATH_RE = re.compile(r"^`([^`]+)`\s*[：:]\s*(.*)$", re.DOTALL)
# Hard placeholder (and similar) hit lines embed ``path`` · label · …
_EMBEDDED_PATH_RE = re.compile(r"`([^`]+)`\s*·")
_SOFT_NOTE_MARKERS = (
    "待核实",
    "示例自注",
    "不阻断验收",
    "含未替换骨架占位",
    "篇幅提醒（软）",
    "素材覆盖提醒（软）",
    "契约软提醒",
)


def path_rejections_from_contract_messages(
    messages: list[str] | None,
) -> dict[str, tuple[str, str]]:
    """Map path → (reason_code, detail) from contract failure / soft_failure copy.

    Soft reminder notes (待核实等) never reject — only hard / cite-shaped messages.
    """
    out: dict[str, tuple[str, str]] = {}
    for raw in messages or []:
        text = str(raw).strip()
        if not text:
            continue
        cite = _CITE_PATH_RE.match(text)
        if cite:
            path = cite.group(1).strip()
            detail = (cite.group(2) or "").strip() or text
            if path:
                out[path] = (REASON_CITATIONS_UNVERIFIED, detail)
            continue
        if any(m in text for m in _SOFT_NOTE_MARKERS):
            continue
        for path in _EMBEDDED_PATH_RE.findall(text):
            p = path.strip()
            if p and p not in out:
                out[p] = (REASON_CONTRACT_FAILED, text)
    return out


def build_file_acceptance(
    files_touched: list[str] | None,
    *,
    phase: RunPhase,
    error: str = "",
    path_rejections: dict[str, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build ordered ``[{path, status, reason?, detail?}]`` for a run's landed files."""
    touched = [p for p in (files_touched or []) if p]
    if not touched:
        return []
    rejections = dict(path_rejections or {})
    out: list[dict[str, Any]] = []

    if phase is RunPhase.FAILED:
        err = (error or "").strip() or "run failed"
        for path in touched:
            reason, detail = rejections.get(path, (REASON_RUN_FAILED, err))
            row: dict[str, Any] = {
                "path": path,
                "status": "rejected",
                "reason": reason,
            }
            if detail:
                row["detail"] = detail
            out.append(row)
        return out

    for path in touched:
        if path in rejections:
            reason, detail = rejections[path]
            row = {"path": path, "status": "rejected", "reason": reason}
            if detail:
                row["detail"] = detail
            out.append(row)
        else:
            out.append({"path": path, "status": "accepted"})
    return out


def accepted_paths(file_acceptance: list[dict[str, Any]] | None) -> list[str]:
    """Paths with status=accepted (stable order)."""
    out: list[str] = []
    for row in file_acceptance or []:
        if not isinstance(row, dict):
            continue
        if row.get("status") == "accepted" and row.get("path"):
            out.append(str(row["path"]))
    return out


def normalize_acceptance_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Wire-safe artifact row, or None if unusable."""
    if not isinstance(row, dict):
        return None
    path = str(row.get("path") or "").strip()
    status = str(row.get("status") or "").strip()
    if not path or status not in ("accepted", "rejected"):
        return None
    out: dict[str, Any] = {"path": path, "status": status}
    reason = str(row.get("reason") or "").strip()
    if reason:
        out["reason"] = reason
    detail = str(row.get("detail") or "").strip()
    if detail:
        out["detail"] = detail
    return out
