"""Path anchors for env file and repo-root resolution."""

from pathlib import Path

_resolved_parents = Path(__file__).resolve().parents
# Repo layout: …/apps/server/agentcore/config/paths.py → parents[4] is the repo root.
# Container layout (Dockerfile COPY agentcore /app/agentcore): fall back to /app
# (parents[2]) instead of IndexError-crashing on import.
PROJECT_ROOT = _resolved_parents[4] if len(_resolved_parents) > 4 else _resolved_parents[2]

# The backend's dotenv lives beside the package at apps/server/.env.
ENV_FILE = _resolved_parents[2] / ".env"
