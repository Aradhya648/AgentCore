"""Pytest wrapper for dogfood manifest structural lint (zero LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
if str(DIR) not in sys.path:
    sys.path.insert(0, str(DIR))

from lint_manifest import EXPECTED_SLOTS, lint  # noqa: E402

MANIFEST = DIR / "manifest.json"


def test_dogfood_manifest_lints_clean() -> None:
    ids = lint(MANIFEST)
    assert len(ids) == EXPECTED_SLOTS
    assert len(set(ids)) == EXPECTED_SLOTS
