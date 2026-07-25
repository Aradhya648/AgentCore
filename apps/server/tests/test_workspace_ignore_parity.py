"""Workspace ignore-list parity ratchet (Python ↔ desktop TypeScript)."""

from __future__ import annotations

from agentcore.workspace import ignore_parity as ip


def test_ignore_lists_aligned():
    result = ip.run_ignore_parity()
    assert result.ok, result.errors


def test_simulate_drift_fails():
    result = ip.run_ignore_parity(simulate_drift=True)
    assert not result.ok
    assert any("__parity_drift_probe__" in e for e in result.errors)


def test_extract_round_trip_nonempty():
    py = ip.py_paths_file().read_text(encoding="utf-8")
    ts = ip.ts_ignore_file().read_text(encoding="utf-8")
    dirs_py = ip.extract_python_set(py, "IGNORED_DIRS")
    dirs_ts = ip.extract_typescript_set(ts, "LIST_FILES_SKIP_DIRS", kind="set")
    assert ".git" in dirs_py
    assert dirs_py == dirs_ts
    sys_py = ip.extract_python_set(py, "SYSTEM_IGNORED_FILE_SUFFIXES")
    assert ".db" in sys_py
    ai_py = ip.extract_python_set(py, "AI_NOISE_FILE_SUFFIXES")
    assert ".png" in ai_py
