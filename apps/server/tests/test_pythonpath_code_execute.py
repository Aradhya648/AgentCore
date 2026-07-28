"""D11′ PYTHONPATH: code_execute auto / TestExitCode card rels share resolve + merge."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentcore.evals.checks import TestExitCodeCheck
from agentcore.evals.types import EvalCase, TurnOutcome
from agentcore.tools.sandbox.pythonpath import (
    default_pythonpath_rels,
    merge_pythonpath_into_env,
    resolve_pythonpath_abs,
)

_REPO = Path(__file__).resolve().parents[3]
_CC = _REPO / "evals" / "code-capability"
_VENDOR_CLICK = _CC / "vendor" / "click@b2e30a175449"


def test_default_pythonpath_rels_detects_src_and_lib(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "lib").mkdir()
    assert default_pythonpath_rels(tmp_path) == [".", "src", "lib"]


def test_default_pythonpath_rels_root_only(tmp_path: Path):
    assert default_pythonpath_rels(tmp_path) == ["."]


def test_resolve_and_merge_match_card_pythonpath(tmp_path: Path):
    (tmp_path / "src").mkdir()
    abs_src = str((tmp_path / "src").resolve())
    assert resolve_pythonpath_abs(tmp_path, ["src"]) == [abs_src]
    env = merge_pythonpath_into_env(
        tmp_path, {"PYTHONPATH": "keep-me"}, rels=["src"]
    )
    assert env["PYTHONPATH"].split(os.pathsep)[0] == abs_src
    assert env["PYTHONPATH"].endswith("keep-me")


def test_auto_merge_includes_src_like_product(tmp_path: Path):
    (tmp_path / "src").mkdir()
    env = merge_pythonpath_into_env(tmp_path, {})
    parts = env["PYTHONPATH"].split(os.pathsep)
    assert str(tmp_path.resolve()) in parts
    assert str((tmp_path / "src").resolve()) in parts


@pytest.mark.skipif(not _VENDOR_CLICK.is_dir(), reason="click vendor missing")
def test_fixed_click_copy_green_with_shared_pythonpath(tmp_path: Path):
    """已修好副本（pristine vendor）：TestExitCode 与 product auto PYTHONPATH 约定测均绿."""
    ws = tmp_path / "click-fixed"
    shutil.copytree(
        _VENDOR_CLICK,
        ws,
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc"),
    )

    cmd = [
        "python",
        "-m",
        "pytest",
        "tests/test_basic.py::test_boolean_conversion",
        "-q",
    ]
    case = EvalCase(
        id="py_path_fixed",
        category="tool_use",
        user_message="x",
        checks=[],
    )
    outcome = TurnOutcome(
        content="ok",
        finish_reason="end_turn",
        rounds=0,
        workspace_root=str(ws),
        reference_root=str(ws),
    )
    check = TestExitCodeCheck(
        command=cmd,
        expected_exit=0,
        timeout_sec=120,
        pythonpath=["src"],
    )
    co = check.run(case, outcome)
    assert co.passed, co.detail

    env = merge_pythonpath_into_env(ws, os.environ.copy())
    proc = subprocess.run(
        cmd,
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
