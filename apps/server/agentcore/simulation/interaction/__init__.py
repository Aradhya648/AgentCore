"""Structured interaction protocols (M3)."""

from agentcore.simulation.interaction.bus import InteractionBus, InteractionTickContext
from agentcore.simulation.interaction.models import (
    InteractionKind,
    InteractionRequest,
    InteractionResult,
    InteractionStateChange,
    InteractionTranscriptLine,
    SimInteractionPayload,
)

__all__ = [
    "InteractionBus",
    "InteractionKind",
    "InteractionRequest",
    "InteractionResult",
    "InteractionStateChange",
    "InteractionTickContext",
    "InteractionTranscriptLine",
    "SimInteractionPayload",
]
