"""Coordinate contract: backend REGION_POSITIONS ↔ protocol-conformance fixture."""

from __future__ import annotations

import json
from pathlib import Path

from agentcore.simulation.world.locations import REGION_POSITIONS

_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "protocol-conformance"
    / "fixtures"
    / "simulation-region-positions.json"
)


def test_region_positions_match_contract_fixture() -> None:
    contract = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    expected = contract["regions"]
    actual = {name: pos.model_dump() for name, pos in REGION_POSITIONS.items()}
    assert actual == expected
