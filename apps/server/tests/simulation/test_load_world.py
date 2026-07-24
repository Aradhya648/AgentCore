"""_load_world fail-fast when tick snapshot is missing."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentcore.core.errors import ValidationError
from agentcore.simulation.service import SimulationService


@pytest.mark.asyncio
async def test_load_world_raises_when_snapshot_missing():
    repo = AsyncMock()
    repo.get_tick = AsyncMock(return_value=None)
    repo.list_agents = AsyncMock(return_value=[])

    svc = SimulationService(repo)

    with pytest.raises(ValidationError, match="missing_tick_snapshot"):
        await svc._load_world("run-missing", current_tick=3)

    repo.get_tick.assert_awaited_once_with("run-missing", 3)
