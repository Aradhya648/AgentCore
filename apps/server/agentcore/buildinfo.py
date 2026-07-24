"""Resolve build provenance (git SHA + build time) at server launch.

The release pipeline is expected to stamp ``GIT_SHA`` / ``BUILT_AT`` into the
environment (deploy doc §7 版本钉定). When they're absent — local dev, or a git
checkout deployed without a pipeline — we fill them in at launch: a best-effort
short SHA from the working tree and the process start time. This keeps
``GET /version`` and the desktop About page meaningful instead of always reading
"unknown". Explicit environment values always win.

This must run *before* ``agentcore.config`` is first imported so the values flow
into ``Settings`` and into every uvicorn reload worker (which inherits the parent
process environment). See ``agentcore.__main__``.
"""

import os
import subprocess
from datetime import UTC, datetime

_GIT_SHA_TIMEOUT_S = 2.0


def _git_short_sha() -> str | None:
    """Best-effort short commit SHA of the working tree, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_SHA_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None  # git missing, not a repo, or timed out
    return result.stdout.strip() or None


def resolve_build_provenance() -> None:
    """Populate ``GIT_SHA`` / ``BUILT_AT`` in ``os.environ`` when not already set.

    Idempotent and override-safe: a value already present (e.g. stamped by the
    release pipeline) is left untouched.
    """
    if not os.environ.get("GIT_SHA"):
        sha = _git_short_sha()
        if sha:
            os.environ["GIT_SHA"] = sha
    if not os.environ.get("BUILT_AT"):
        os.environ["BUILT_AT"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
