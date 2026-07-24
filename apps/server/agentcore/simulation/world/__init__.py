"""World engine package."""

from agentcore.simulation.world.locations import LOCATION_NEIGHBORS, LOCATIONS, REGION_POSITIONS

__all__ = [
    "LOCATIONS",
    "LOCATION_NEIGHBORS",
    "REGION_POSITIONS",
    "WorldAgent",
    "WorldEngine",
    "WorldState",
]


def __getattr__(name: str):
    if name in ("WorldAgent", "WorldState"):
        from agentcore.simulation.world.state import WorldAgent, WorldState

        return WorldAgent if name == "WorldAgent" else WorldState
    if name == "WorldEngine":
        from agentcore.simulation.world.engine import WorldEngine

        return WorldEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
