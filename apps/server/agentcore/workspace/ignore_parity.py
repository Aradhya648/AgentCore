"""Workspace ignore-list parity: Python ``_paths`` ↔ desktop ``workspaceIgnore``.

Two-tier hide rules are hand-maintained on both sides (双模式工作区 · 系统文件隐藏).
This module extracts the three sets from each source file and fails when they
diverge — no codegen, minimal ratchet (same spirit as DebateForm member snapshot).

Run::

    uv run python scripts/check_workspace_ignore_parity.py
    uv run python scripts/check_workspace_ignore_parity.py --simulate-drift
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SERVER_ROOT = Path(__file__).resolve().parents[2]
_PY_PATHS = Path(__file__).resolve().parent / "_paths.py"
_TS_IGNORE = (
    _SERVER_ROOT.parent / "desktop" / "src" / "main" / "fs" / "workspaceIgnore.ts"
)

# (label, python name, typescript name, ts kind)
_SETS: tuple[tuple[str, str, str, str], ...] = (
    ("dirs", "IGNORED_DIRS", "LIST_FILES_SKIP_DIRS", "set"),
    (
        "system_suffixes",
        "SYSTEM_IGNORED_FILE_SUFFIXES",
        "SYSTEM_IGNORED_FILE_SUFFIXES",
        "array",
    ),
    (
        "ai_noise_suffixes",
        "AI_NOISE_FILE_SUFFIXES",
        "AI_NOISE_FILE_SUFFIXES",
        "array",
    ),
)

_STRING_LIT = re.compile(r'"([^"]+)"')


@dataclass(frozen=True)
class IgnoreParityResult:
    ok: bool
    errors: list[str]
    py_path: Path
    ts_path: Path


def py_paths_file() -> Path:
    return _PY_PATHS


def ts_ignore_file() -> Path:
    return _TS_IGNORE


def _quoted_strings(block: str) -> frozenset[str]:
    return frozenset(_STRING_LIT.findall(block))


def extract_python_set(src: str, name: str) -> frozenset[str]:
    """Pull members from ``NAME: frozenset[str] = frozenset({...})``."""
    m = re.search(
        rf"{re.escape(name)}\s*:\s*frozenset\[str\]\s*=\s*frozenset\(\s*\{{(.*?)\}}\s*\)",
        src,
        flags=re.DOTALL,
    )
    if not m:
        raise ValueError(f"Python set {name!r} not found in {_PY_PATHS.name}")
    return _quoted_strings(m.group(1))


def extract_typescript_set(src: str, name: str, *, kind: str) -> frozenset[str]:
    """Pull members from ``export const NAME = new Set([...])`` or ``[…] as const``."""
    if kind == "set":
        pat = rf"export const {re.escape(name)}\s*=\s*new Set\(\[(.*?)\]\)"
    elif kind == "array":
        pat = rf"export const {re.escape(name)}\s*=\s*\[(.*?)\]\s*as const"
    else:
        raise ValueError(f"unknown ts kind {kind!r}")
    m = re.search(pat, src, flags=re.DOTALL)
    if not m:
        raise ValueError(f"TypeScript {kind} {name!r} not found in {_TS_IGNORE.name}")
    return _quoted_strings(m.group(1))


def _diff_line(label: str, only_py: frozenset[str], only_ts: frozenset[str]) -> str | None:
    if not only_py and not only_ts:
        return None
    parts: list[str] = [f"{label}:"]
    if only_py:
        parts.append(f" only-in-Python={sorted(only_py)}")
    if only_ts:
        parts.append(f" only-in-TypeScript={sorted(only_ts)}")
    return "".join(parts)


def compare_sources(
    py_src: str,
    ts_src: str,
    *,
    simulate_drift: bool = False,
) -> list[str]:
    """Return human-readable mismatch lines (empty ⇒ aligned)."""
    errors: list[str] = []
    for label, py_name, ts_name, ts_kind in _SETS:
        py_set = extract_python_set(py_src, py_name)
        ts_set = extract_typescript_set(ts_src, ts_name, kind=ts_kind)
        if simulate_drift and label == "dirs":
            # Inject a phantom member on the TS side so the gate must fail.
            ts_set = ts_set | {"__parity_drift_probe__"}
        line = _diff_line(label, py_set - ts_set, ts_set - py_set)
        if line:
            errors.append(line)
        if not py_set:
            errors.append(f"{label}: Python set is empty (parse failure?)")
        if not ts_set and not simulate_drift:
            errors.append(f"{label}: TypeScript set is empty (parse failure?)")
    return errors


def run_ignore_parity(*, simulate_drift: bool = False) -> IgnoreParityResult:
    """Compare on-disk ignore lists; ``simulate_drift`` expects failure."""
    if not _PY_PATHS.is_file():
        return IgnoreParityResult(
            ok=False,
            errors=[f"missing Python source: {_PY_PATHS}"],
            py_path=_PY_PATHS,
            ts_path=_TS_IGNORE,
        )
    if not _TS_IGNORE.is_file():
        return IgnoreParityResult(
            ok=False,
            errors=[f"missing TypeScript source: {_TS_IGNORE}"],
            py_path=_PY_PATHS,
            ts_path=_TS_IGNORE,
        )
    try:
        errors = compare_sources(
            _PY_PATHS.read_text(encoding="utf-8"),
            _TS_IGNORE.read_text(encoding="utf-8"),
            simulate_drift=simulate_drift,
        )
    except ValueError as e:
        errors = [str(e)]
    return IgnoreParityResult(
        ok=not errors,
        errors=errors,
        py_path=_PY_PATHS,
        ts_path=_TS_IGNORE,
    )
