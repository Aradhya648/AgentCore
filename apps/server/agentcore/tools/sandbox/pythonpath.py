"""Shared PYTHONPATH resolution for ``code_execute`` and ``TestExitCode`` (D11′).

Product path auto-injects workspace root plus existing ``src`` / ``lib`` (src-layout /
lib-layout pure trees). Eval hard checks pass explicit ``pythonpath`` rels from the
card so both sides resolve relative dirs the same way against cwd.
"""

from __future__ import annotations

import os
from pathlib import Path

_AUTO_EXTRA = ("src", "lib")


def default_pythonpath_rels(cwd: Path) -> list[str]:
    """Product default: ``.`` + existing ``src`` / ``lib`` dirs under ``cwd``."""
    root = Path(cwd)
    rels = ["."]
    for name in _AUTO_EXTRA:
        if (root / name).is_dir():
            rels.append(name)
    return rels


def resolve_pythonpath_abs(cwd: Path, rels: list[str] | None = None) -> list[str]:
    """Absolute dirs for PYTHONPATH. ``rels=None`` → :func:`default_pythonpath_rels`."""
    root = Path(cwd)
    use = list(rels) if rels is not None else default_pythonpath_rels(root)
    if not use:
        use = ["."]
    out: list[str] = []
    for rel in use:
        entry = root if rel in (".", "") else (root / rel)
        out.append(str(entry.resolve()))
    return out


def merge_pythonpath_into_env(
    cwd: Path,
    env: dict[str, str],
    *,
    rels: list[str] | None = None,
) -> dict[str, str]:
    """Prepend resolved entries to ``PYTHONPATH`` (keep existing / site-packages)."""
    merged = dict(env)
    prev = merged.get("PYTHONPATH", "")
    entries = resolve_pythonpath_abs(cwd, rels)
    merged["PYTHONPATH"] = os.pathsep.join(filter(None, [*entries, prev]))
    return merged
