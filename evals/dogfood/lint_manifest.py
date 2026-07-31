#!/usr/bin/env python3
"""Zero-LLM structural lint for evals/dogfood/manifest.json.

Exit 0 on success; non-zero on missing fields, duplicate ids, or count != 20.

Usage (repo root):
  python evals/dogfood/lint_manifest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

EXPECTED_SLOTS = 20
DIMENSIONS = ("routing", "deliverable", "citation")
KINDS = frozenset({"synthetic_fill", "pending_label"})
EVIDENCE_TIERS = frozenset({"L1_synthetic", "dogfood", "R_repo"})
SCORE_INTS = frozenset({0, 1, 2})

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "manifest.json"


class LintError(Exception):
    pass


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise LintError(msg)


def _is_null_id(value: Any) -> bool:
    return value is None


def _validate_score_value(value: Any, *, path: str) -> None:
    if value == "N/A":
        return
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value in SCORE_INTS,
        f"{path}: score must be 0|1|2 or \"N/A\", got {value!r}",
    )


def _validate_label_cell(cell: Any, *, path: str, allow_null: bool) -> None:
    if cell is None:
        _require(allow_null, f"{path}: null not allowed here")
        return
    _require(isinstance(cell, dict), f"{path}: expected object or null")
    _require("score" in cell, f"{path}: missing score")
    _validate_score_value(cell["score"], path=f"{path}.score")
    if "note" in cell and cell["note"] is not None:
        _require(isinstance(cell["note"], str), f"{path}.note: must be string")


def _labels_all_null(labels: dict[str, Any]) -> bool:
    return all(labels.get(d) is None for d in DIMENSIONS)


def _validate_entry(entry: Any, *, index: int) -> str:
    _require(isinstance(entry, dict), f"entries[{index}]: must be object")
    eid = entry.get("id")
    _require(isinstance(eid, str) and eid.strip(), f"entries[{index}]: id must be non-empty string")
    prefix = f"entries[{index}] ({eid})"

    kind = entry.get("kind")
    _require(kind in KINDS, f"{prefix}: kind must be one of {sorted(KINDS)}")

    tier = entry.get("evidence_tier")
    _require(tier in EVIDENCE_TIERS, f"{prefix}: evidence_tier must be one of {sorted(EVIDENCE_TIERS)}")

    for field in ("scenario", "intended_coverage"):
        val = entry.get(field)
        _require(isinstance(val, str) and val.strip(), f"{prefix}: {field} must be non-empty string")

    for id_field in ("conversation_id", "trace_id"):
        _require(id_field in entry, f"{prefix}: missing {id_field}")
        val = entry[id_field]
        _require(
            _is_null_id(val) or (isinstance(val, str) and val.strip()),
            f"{prefix}: {id_field} must be null or non-empty string (no fabricated placeholders)",
        )

    labels = entry.get("labels")
    _require(isinstance(labels, dict), f"{prefix}: labels must be object")
    for dim in DIMENSIONS:
        _require(dim in labels, f"{prefix}: labels missing {dim}")

    if kind == "synthetic_fill":
        _require(
            tier == "L1_synthetic",
            f"{prefix}: synthetic_fill requires evidence_tier=L1_synthetic",
        )
        for dim in DIMENSIONS:
            _validate_label_cell(labels[dim], path=f"{prefix}.labels.{dim}", allow_null=False)
    else:
        # pending_label: all-null (awaiting fill) OR fully scored (backfilled from logs)
        if _labels_all_null(labels):
            for dim in DIMENSIONS:
                _validate_label_cell(labels[dim], path=f"{prefix}.labels.{dim}", allow_null=True)
        else:
            for dim in DIMENSIONS:
                _validate_label_cell(labels[dim], path=f"{prefix}.labels.{dim}", allow_null=False)
            _require(
                tier == "dogfood",
                f"{prefix}: scored pending_label should use evidence_tier=dogfood",
            )

    return eid


def validate_manifest(data: Any) -> list[str]:
    _require(isinstance(data, dict), "manifest root must be object")
    _require(data.get("schema_version") == 1, "schema_version must be 1")
    _require(data.get("slot_count") == EXPECTED_SLOTS, f"slot_count must be {EXPECTED_SLOTS}")
    _require(data.get("gate_policy") == "observe_only", "gate_policy must be observe_only")

    dims = data.get("dimensions")
    _require(dims == list(DIMENSIONS), f"dimensions must be {list(DIMENSIONS)}")

    entries = data.get("entries")
    _require(isinstance(entries, list), "entries must be array")
    _require(
        len(entries) == EXPECTED_SLOTS,
        f"entries length must be {EXPECTED_SLOTS}, got {len(entries)}",
    )

    seen: set[str] = set()
    order: list[str] = []
    for i, entry in enumerate(entries):
        eid = _validate_entry(entry, index=i)
        _require(eid not in seen, f"duplicate entry id: {eid}")
        seen.add(eid)
        order.append(eid)
    return order


def lint(path: Path | None = None) -> list[str]:
    target = path or MANIFEST_PATH
    _require(target.is_file(), f"manifest not found: {target}")
    data = json.loads(target.read_text(encoding="utf-8"))
    return validate_manifest(data)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else MANIFEST_PATH
    try:
        ids = lint(path)
    except (OSError, json.JSONDecodeError, LintError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {path} — {len(ids)} slots, ids unique")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
