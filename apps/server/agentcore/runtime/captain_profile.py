"""CEO captain profile tweaks (round budget, etc.)."""

from __future__ import annotations

from dataclasses import replace

from agentcore.config import settings
from agentcore.llm.profiles import ProfileParams


def apply_captain_max_rounds(profile: ProfileParams) -> ProfileParams:
    """Raise CEO max_rounds to ``engine_captain_max_rounds`` when configured higher."""
    cap = settings.engine_captain_max_rounds
    if cap <= 0 or profile.max_rounds >= cap:
        return profile
    return replace(profile, max_rounds=cap)
