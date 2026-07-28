"""R4 回归棘轮单元测（无 vendor 矩阵、无 LLM）。"""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

_CC = Path(__file__).resolve().parent
_R4 = _CC / "r4_regress.py"

sys.path.insert(0, str(_CC))

from r4_regress import (  # noqa: E402
    DEFAULT_TOLERANCE_PP,
    compare_pass_rate,
    pass_rate_from_report,
)


def _minimal_report(*, passed: int, cells: int) -> dict:
    return {
        "summary": {
            "pass": passed,
            "fail": cells - passed,
            "matrix_cells": cells,
            "hard_accept": passed == cells,
        }
    }


def test_pass_rate_from_cells():
    assert pass_rate_from_report(_minimal_report(passed=56, cells=56)) == 1.0
    assert pass_rate_from_report(_minimal_report(passed=45, cells=50)) == 0.9


def test_compare_equal_ok():
    base = _minimal_report(passed=100, cells=100)
    regressed, detail, cur, b = compare_pass_rate(base, base, tolerance_pp=10)
    assert not regressed
    assert cur == b == 1.0
    assert "OK" in detail


def test_compare_drop_11pp_fails():
    base = _minimal_report(passed=100, cells=100)
    cur = _minimal_report(passed=89, cells=100)  # -11pp
    regressed, detail, _, _ = compare_pass_rate(cur, base, tolerance_pp=10)
    assert regressed
    assert "Fail" in detail


def test_compare_drop_5pp_within_tolerance():
    base = _minimal_report(passed=100, cells=100)
    cur = _minimal_report(passed=95, cells=100)  # -5pp
    regressed, _, _, _ = compare_pass_rate(cur, base, tolerance_pp=10)
    assert not regressed


def test_compare_improvement_ok():
    base = _minimal_report(passed=80, cells=100)
    cur = _minimal_report(passed=90, cells=100)
    regressed, _, _, _ = compare_pass_rate(cur, base, tolerance_pp=10)
    assert not regressed


def test_frozen_baselines_exist_and_match_latest():
    for phase in ("r1", "r2", "r3"):
        frozen = _CC / "reports" / "baselines" / f"{phase}.json"
        latest = _CC / "reports" / f"{phase}_baseline_latest.json"
        assert frozen.is_file(), frozen
        assert latest.is_file(), latest
        a = json.loads(frozen.read_text(encoding="utf-8"))
        b = json.loads(latest.read_text(encoding="utf-8"))
        regressed, detail, _, _ = compare_pass_rate(
            b, a, tolerance_pp=DEFAULT_TOLERANCE_PP
        )
        assert not regressed, detail


def test_cli_compare_latest_green():
    proc = subprocess.run(
        [sys.executable, str(_R4), "--compare-latest"],
        cwd=_CC.parents[1],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK" in proc.stdout


def test_cli_self_test_regression():
    proc = subprocess.run(
        [sys.executable, str(_R4), "--self-test-regression"],
        cwd=_CC.parents[1],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cli_compare_synthetic_regression(tmp_path: Path):
    frozen = _CC / "reports" / "baselines" / "r1.json"
    baseline = json.loads(frozen.read_text(encoding="utf-8"))
    bad = deepcopy(baseline)
    cells = int(bad["summary"]["matrix_cells"])
    bad["summary"]["pass"] = max(0, cells - max(1, int(round(cells * 0.11))))
    bad["summary"]["fail"] = cells - bad["summary"]["pass"]
    bad_path = tmp_path / "r1_bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(_R4),
            "--compare",
            str(bad_path),
            "--phase",
            "r1",
        ],
        cwd=_CC.parents[1],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "Fail" in proc.stdout or "回归" in proc.stdout


def test_update_baseline_requires_reason(tmp_path: Path):
    src = _CC / "reports" / "r1_baseline_latest.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(_R4),
            "--update-baseline",
            "--phase",
            "r1",
            "--from",
            str(src),
            "--reason",
            "",
        ],
        cwd=_CC.parents[1],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
