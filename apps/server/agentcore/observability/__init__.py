"""Product AI observability: event registry + query layer.

Stay inside ``apps/server`` (no separate package). The single emit style is
``get_logger(__name__)`` + ``logger.info("component.action", ...)`` — the
registry check runs inside the structlog processor chain, so callsite
anchoring (``logger`` / ``func_name`` / ``lineno``) stays on the caller.
"""

from agentcore.observability.events import (
    EventRegistry,
    EventSpec,
    FieldType,
    UnregisteredLogEventError,
    UnregisteredLogEventWarning,
    check_event_registered,
    get_registry,
    registry_processor,
)

__all__ = [
    "EventRegistry",
    "EventSpec",
    "FieldType",
    "UnregisteredLogEventError",
    "UnregisteredLogEventWarning",
    "check_event_registered",
    "get_registry",
    "registry_processor",
]
