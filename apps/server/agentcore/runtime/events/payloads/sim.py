"""AI Town simulation SSE payload wire models.

Unlike the chat/run families (factory-built dicts), the ``sim.*`` events are emitted as
``model_dump()`` of PRODUCTION pydantic models — so those models ARE the wire source and
are reused here directly (no descriptive twins). The TS emission specs in ``__init__``
mark server-defaulted fields ``force_required`` where the dump always includes them.

``SimTickFramePayload`` is the one exception: its payload is an inline dict in
``simulation/service.py`` (replay frame), described here.
"""

from __future__ import annotations

from typing import Any

from agentcore.runtime.events.payloads._base import WirePayload

# Re-exported for the registry: production wire models (single source, reused).
from agentcore.simulation.interaction.models import (  # noqa: F401
    InteractionResult,
    InteractionStateChange,
    InteractionTranscriptLine,
    SimInteractionPayload,
)
from agentcore.simulation.observe.types import TickMetrics  # noqa: F401
from agentcore.simulation.types import (  # noqa: F401
    SimAgentAction,
    SimAgentActionPayload,
    SimAgentState,
    SimAgentStatePayload,
    SimTickEndedPayload,
    SimTickStartedPayload,
    SimWorldEventPayload,
    WorldEventWire,
    WorldModifiersWire,
)
from agentcore.simulation.vec3 import Vec3  # noqa: F401


class SimTickFramePayload(WirePayload):
    """One persisted world frame on tick replay (``simulation/service.py`` replay path).
    `snapshot` is the verbatim ``SimTickSnapshot`` dump persisted on the tick row."""

    run_id: str
    tick_number: int
    snapshot: dict[str, Any]
