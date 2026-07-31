#!/usr/bin/env python3
"""Semi-auto backfill of dogfood ``pending_label`` slots from log evidence.

Writes real ``conversation_id`` / ``trace_id`` from an investigation pack or
``decision_spine`` / ``log_timeline --json`` payload. Never invents production
IDs; never auto-scores (scores stay null unless all three dims are passed).

Usage (repo root):
  python evals/dogfood/fill_from_pack.py --pack <dir> [--slot id|--coverage substr]
  python evals/dogfood/fill_from_pack.py --spine <spine-or-timeline.json>
  python evals/dogfood/fill_from_pack.py --trace-id TID --conversation-id CID
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lint_manifest import DIMENSIONS, LintError, lint, validate_manifest

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT / "manifest.json"
PACK_REQUIRED = ("decision_spine.json", "meta.json")
SCORE_INTS = frozenset({0, 1, 2})


class FillError(Exception):
    pass


def _nonempty_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_empty_pending(entry: dict[str, Any]) -> bool:
    if entry.get("kind") != "pending_label":
        return False
    return entry.get("conversation_id") is None and entry.get("trace_id") is None


def extract_ids_from_pack(pack_dir: Path) -> tuple[str | None, str | None]:
    """Prefer ``meta.json``; fall back to ``decision_spine.json``."""
    if not pack_dir.is_dir():
        raise FillError(f"pack dir not found: {pack_dir}")
    for name in PACK_REQUIRED:
        if not (pack_dir / name).is_file():
            raise FillError(f"pack missing required file: {name}")

    meta = json.loads((pack_dir / "meta.json").read_text(encoding="utf-8-sig"))
    spine = json.loads(
        (pack_dir / "decision_spine.json").read_text(encoding="utf-8-sig")
    )

    cid = _nonempty_str(meta.get("conversation_id")) or _nonempty_str(
        spine.get("conversation_id")
    )
    tid = _nonempty_str(meta.get("trace_id")) or _nonempty_str(spine.get("trace_id"))
    if not cid and not tid:
        raise FillError("pack has neither conversation_id nor trace_id")
    return cid, tid


def extract_ids_from_spine_payload(data: Any) -> tuple[str | None, str | None]:
    """Accept bare decision_spine or ``log_timeline --json`` (mode=trace) envelope."""
    if not isinstance(data, dict):
        raise FillError("spine payload must be a JSON object")

    spine: dict[str, Any]
    meta: dict[str, Any] = {}
    if "decision_spine" in data and isinstance(data["decision_spine"], dict):
        spine = data["decision_spine"]
        if isinstance(data.get("meta"), dict):
            meta = data["meta"]
    elif data.get("schema_version") or "decisions" in data or "head" in data:
        spine = data
    else:
        raise FillError(
            "unrecognized JSON: need decision_spine object or timeline --json envelope"
        )

    cid = _nonempty_str(meta.get("conversation_id")) or _nonempty_str(
        spine.get("conversation_id")
    )
    tid = _nonempty_str(meta.get("trace_id")) or _nonempty_str(spine.get("trace_id"))
    if not cid and not tid:
        raise FillError("payload has neither conversation_id nor trace_id")
    return cid, tid


def select_slot(
    entries: list[dict[str, Any]],
    *,
    slot_id: str | None,
    coverage: str | None,
    force: bool,
) -> dict[str, Any]:
    if slot_id:
        for entry in entries:
            if entry.get("id") == slot_id:
                if entry.get("kind") != "pending_label":
                    raise FillError(f"slot {slot_id!r} is not pending_label")
                if not force and not _is_empty_pending(entry):
                    raise FillError(
                        f"slot {slot_id!r} already has ids; pass --force to overwrite"
                    )
                return entry
        raise FillError(f"slot not found: {slot_id}")

    candidates = [e for e in entries if _is_empty_pending(e)]
    if coverage:
        needle = coverage.strip().lower()
        matched = [
            e
            for e in candidates
            if needle in str(e.get("intended_coverage") or "").lower()
        ]
        if not matched:
            raise FillError(
                f"no empty pending_label with intended_coverage matching {coverage!r}"
            )
        return matched[0]

    if not candidates:
        raise FillError("no empty pending_label slots left")
    return candidates[0]


def _parse_score(raw: str | None, *, name: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    text = raw.strip()
    if text.upper() == "N/A":
        return {"score": "N/A"}
    try:
        value = int(text)
    except ValueError as exc:
        raise FillError(f"--{name} must be 0|1|2|N/A, got {raw!r}") from exc
    if value not in SCORE_INTS:
        raise FillError(f"--{name} must be 0|1|2|N/A, got {raw!r}")
    return {"score": value}


def apply_optional_scores(
    entry: dict[str, Any],
    *,
    routing: str | None,
    deliverable: str | None,
    citation: str | None,
) -> None:
    provided = {
        "routing": routing,
        "deliverable": deliverable,
        "citation": citation,
    }
    if all(v is None for v in provided.values()):
        return
    if any(v is None for v in provided.values()):
        raise FillError(
            "scoring is all-or-nothing: pass --routing, --deliverable, and --citation "
            "together (or omit all to leave labels null)"
        )
    labels: dict[str, Any] = {}
    for dim in DIMENSIONS:
        cell = _parse_score(provided[dim], name=dim)
        assert cell is not None
        labels[dim] = cell
    entry["labels"] = labels
    entry["evidence_tier"] = "dogfood"


def fill_entry(
    entry: dict[str, Any],
    *,
    conversation_id: str | None,
    trace_id: str | None,
    routing: str | None = None,
    deliverable: str | None = None,
    citation: str | None = None,
) -> None:
    if not conversation_id and not trace_id:
        raise FillError("refuse to write: both ids empty (no fabrication)")
    entry["conversation_id"] = conversation_id
    entry["trace_id"] = trace_id
    entry["evidence_tier"] = "dogfood"
    entry["kind"] = "pending_label"
    apply_optional_scores(
        entry, routing=routing, deliverable=deliverable, citation=citation
    )


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FillError(f"manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        validate_manifest(data)
    except LintError as exc:
        raise FillError(f"manifest failed lint before fill: {exc}") from exc
    return data


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_ids(args: argparse.Namespace) -> tuple[str | None, str | None]:
    sources = sum(
        bool(x)
        for x in (args.pack, args.spine, args.trace_id or args.conversation_id)
    )
    if sources != 1:
        raise FillError(
            "provide exactly one evidence source: --pack | --spine | "
            "(--trace-id and/or --conversation-id)"
        )

    if args.pack:
        return extract_ids_from_pack(Path(args.pack))
    if args.spine:
        path = Path(args.spine)
        if not path.is_file():
            raise FillError(f"spine file not found: {path}")
        return extract_ids_from_spine_payload(
            json.loads(path.read_text(encoding="utf-8-sig"))
        )

    cid = _nonempty_str(args.conversation_id)
    tid = _nonempty_str(args.trace_id)
    if not cid and not tid:
        raise FillError("need --trace-id and/or --conversation-id")
    return cid, tid


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Fill one empty dogfood pending_label from pack / decision_spine evidence. "
            "Does not invent IDs; does not auto-score."
        )
    )
    p.add_argument(
        "--pack",
        help="investigation pack dir (decision_spine.json + meta.json)",
    )
    p.add_argument(
        "--spine",
        help="decision_spine.json or log_timeline --json output file",
    )
    p.add_argument("--trace-id", dest="trace_id", help="explicit trace_id from logs")
    p.add_argument(
        "--conversation-id",
        dest="conversation_id",
        help="explicit conversation_id from logs",
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"manifest path (default: {DEFAULT_MANIFEST})",
    )
    p.add_argument("--slot", help="pending_label entry id to fill")
    p.add_argument(
        "--coverage",
        help="pick first empty pending_label whose intended_coverage contains this",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite ids on a non-empty pending_label slot",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print selection + ids; do not write manifest",
    )
    p.add_argument("--routing", help="optional score 0|1|2|N/A (requires all three dims)")
    p.add_argument("--deliverable", help="optional score 0|1|2|N/A")
    p.add_argument("--citation", help="optional score 0|1|2|N/A")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cid, tid = resolve_ids(args)
        data = load_manifest(args.manifest)
        entries = data["entries"]
        assert isinstance(entries, list)
        entry = select_slot(
            entries, slot_id=args.slot, coverage=args.coverage, force=args.force
        )
        fill_entry(
            entry,
            conversation_id=cid,
            trace_id=tid,
            routing=args.routing,
            deliverable=args.deliverable,
            citation=args.citation,
        )
        validate_manifest(data)

        summary = {
            "slot": entry["id"],
            "intended_coverage": entry.get("intended_coverage"),
            "conversation_id": cid,
            "trace_id": tid,
            "evidence_tier": entry.get("evidence_tier"),
            "labels_scored": not all(
                entry.get("labels", {}).get(d) is None for d in DIMENSIONS
            ),
            "dry_run": bool(args.dry_run),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        if args.dry_run:
            return 0

        write_manifest(args.manifest, data)
        lint(args.manifest)
        print(f"OK: wrote {args.manifest} — slot {entry['id']}", file=sys.stderr)
        return 0
    except (OSError, json.JSONDecodeError, FillError, LintError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
