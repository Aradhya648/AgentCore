"""Tests for dogfood fill_from_pack (P2 log → pending_label)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parent
if str(DIR) not in sys.path:
    sys.path.insert(0, str(DIR))

from fill_from_pack import (  # noqa: E402
    extract_ids_from_pack,
    extract_ids_from_spine_payload,
    fill_entry,
    main,
    select_slot,
)
from lint_manifest import lint  # noqa: E402

MANIFEST = DIR / "manifest.json"
TID = "a" * 32
CID = "11111111-2222-3333-4444-555555555555"


def _write_pack(pack_dir: Path, *, cid: str | None = CID, tid: str | None = TID) -> None:
    pack_dir.mkdir(parents=True, exist_ok=True)
    spine = {
        "schema_version": "decision_spine.v0",
        "trace_id": tid,
        "conversation_id": cid,
        "head": {},
        "decisions": [],
        "llm": {},
        "tail": {"source": "none"},
        "cost": {},
        "health": {},
    }
    meta = {
        "schema_version": "investigation_pack.v0",
        "trace_id": tid,
        "conversation_id": cid,
        "files": ["decision_spine.json", "timeline.jsonl", "meta.json"],
    }
    (pack_dir / "decision_spine.json").write_text(
        json.dumps(spine), encoding="utf-8"
    )
    (pack_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (pack_dir / "timeline.jsonl").write_text("", encoding="utf-8")


@pytest.fixture()
def manifest_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "manifest.json"
    shutil.copy(MANIFEST, dest)
    return dest


def test_extract_ids_from_pack(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    cid, tid = extract_ids_from_pack(pack)
    assert cid == CID
    assert tid == TID


def test_extract_ids_from_timeline_json_envelope() -> None:
    payload = {
        "mode": "trace",
        "decision_spine": {
            "schema_version": "decision_spine.v0",
            "trace_id": TID,
            "conversation_id": CID,
        },
        "meta": {"conversation_id": CID},
    }
    cid, tid = extract_ids_from_spine_payload(payload)
    assert cid == CID
    assert tid == TID


def test_select_slot_by_coverage() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = select_slot(data["entries"], slot_id=None, coverage="验收缺口", force=False)
    assert entry["id"] == "df_pend_08_acceptance_unmet"


def test_fill_refuses_empty_ids() -> None:
    entry = {
        "id": "x",
        "kind": "pending_label",
        "evidence_tier": "dogfood",
        "labels": {"routing": None, "deliverable": None, "citation": None},
    }
    with pytest.raises(Exception, match="refuse"):
        fill_entry(entry, conversation_id=None, trace_id=None)


def test_cli_pack_fills_empty_slot(manifest_copy: Path, tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    rc = main(
        [
            "--pack",
            str(pack),
            "--manifest",
            str(manifest_copy),
            "--slot",
            "df_pend_07_should_delegate_but_solo",
        ]
    )
    assert rc == 0
    data = json.loads(manifest_copy.read_text(encoding="utf-8"))
    entry = next(e for e in data["entries"] if e["id"] == "df_pend_07_should_delegate_but_solo")
    assert entry["conversation_id"] == CID
    assert entry["trace_id"] == TID
    assert entry["evidence_tier"] == "dogfood"
    assert entry["kind"] == "pending_label"
    assert entry["labels"]["routing"] is None
    lint(manifest_copy)


def test_cli_dry_run_does_not_write(manifest_copy: Path, tmp_path: Path) -> None:
    before = manifest_copy.read_text(encoding="utf-8")
    pack = tmp_path / "pack"
    _write_pack(pack)
    rc = main(
        [
            "--pack",
            str(pack),
            "--manifest",
            str(manifest_copy),
            "--coverage",
            "该委派却直扛",
            "--dry-run",
        ]
    )
    assert rc == 0
    assert manifest_copy.read_text(encoding="utf-8") == before


def test_cli_optional_scores(manifest_copy: Path, tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    rc = main(
        [
            "--pack",
            str(pack),
            "--manifest",
            str(manifest_copy),
            "--slot",
            "df_pend_10_empty_shell_report",
            "--routing",
            "2",
            "--deliverable",
            "0",
            "--citation",
            "N/A",
        ]
    )
    assert rc == 0
    data = json.loads(manifest_copy.read_text(encoding="utf-8"))
    entry = next(e for e in data["entries"] if e["id"] == "df_pend_10_empty_shell_report")
    assert entry["labels"]["routing"]["score"] == 2
    assert entry["labels"]["deliverable"]["score"] == 0
    assert entry["labels"]["citation"]["score"] == "N/A"
    lint(manifest_copy)


def test_cli_partial_scores_rejected(manifest_copy: Path, tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    _write_pack(pack)
    rc = main(
        [
            "--pack",
            str(pack),
            "--manifest",
            str(manifest_copy),
            "--slot",
            "df_pend_07_should_delegate_but_solo",
            "--routing",
            "1",
        ]
    )
    assert rc == 1
