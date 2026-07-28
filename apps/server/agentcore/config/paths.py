"""Path anchors for env file and repo-root resolution."""

from __future__ import annotations

import os
from pathlib import Path

_resolved_parents = Path(__file__).resolve().parents
# Repo layout: …/apps/server/agentcore/config/paths.py → parents[4] is the repo root.
# Container layout (Dockerfile COPY agentcore /app/agentcore): fall back to /app
# (parents[2]) instead of IndexError-crashing on import.
PROJECT_ROOT = _resolved_parents[4] if len(_resolved_parents) > 4 else _resolved_parents[2]

# The backend's dotenv lives beside the package at apps/server/.env (or .env.{env}).
_SERVER_DIR = _resolved_parents[2]


def resolve_env_file(
    env_name: str | None = None,
    *,
    server_dir: Path | None = None,
) -> Path:
    """Pick dotenv path from ``AGENTCORE_ENV`` (default ``development`` → ``.env``).

    Non-development: prefer ``.env.{env}`` when that file exists, else ``.env``.
    Selection reads the process environment only (not values inside the dotenv).
    """
    raw = env_name if env_name is not None else os.environ.get("AGENTCORE_ENV", "development")
    name = (raw or "").strip() or "development"
    base = server_dir if server_dir is not None else _SERVER_DIR
    default = base / ".env"
    if name == "development":
        return default
    specific = base / f".env.{name}"
    return specific if specific.is_file() else default


ENV_FILE = resolve_env_file()
