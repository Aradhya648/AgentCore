"""Central product-AI log event registry (就地立约).

Call sites emit via ``get_logger(__name__)`` + ``logger.info("component.action",
...)`` — the only emit style. Validation runs in the structlog processor chain
(:func:`registry_processor`, wired in ``core/logging.py``), so unregistered
names warn in dev / pass in prod without touching any call site.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

FieldTypeName = Literal["str", "int", "float", "bool", "list", "dict", "any"]


@dataclass(frozen=True, slots=True)
class FieldType:
    """Lightweight field type tag (not a full JSON Schema)."""

    name: FieldTypeName

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name


@dataclass(frozen=True, slots=True)
class EventSpec:
    """One registered structured log event."""

    name: str
    description: str = ""
    fields: Mapping[str, FieldType] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if "." not in self.name:
            raise ValueError(f"event name must be component.action, got {self.name!r}")


class UnregisteredLogEventError(LookupError):
    """Raised in strict-dev mode when an event name is not in the registry."""


class UnregisteredLogEventWarning(UserWarning):
    """Emitted in non-strict debug when an event name is not registered."""


@runtime_checkable
class EventRegistry(Protocol):
    """Read-only registry of known product-AI log events."""

    def get(self, name: str) -> EventSpec | None: ...

    def requires(self, name: str) -> EventSpec: ...

    def __contains__(self, name: object) -> bool: ...

    def names(self) -> frozenset[str]: ...

    def all_specs(self) -> tuple[EventSpec, ...]: ...


class MapEventRegistry:
    """In-memory :class:`EventRegistry` backed by a name→spec map."""

    def __init__(self, specs: list[EventSpec] | tuple[EventSpec, ...]) -> None:
        by_name: dict[str, EventSpec] = {}
        for spec in specs:
            if spec.name in by_name:
                raise ValueError(f"duplicate event registration: {spec.name!r}")
            by_name[spec.name] = spec
        self._by_name = by_name
        self._names = frozenset(by_name)

    def get(self, name: str) -> EventSpec | None:
        return self._by_name.get(name)

    def requires(self, name: str) -> EventSpec:
        spec = self.get(name)
        if spec is None:
            raise UnregisteredLogEventError(name)
        return spec

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._by_name

    def names(self) -> frozenset[str]:
        return self._names

    def all_specs(self) -> tuple[EventSpec, ...]:
        return tuple(self._by_name[n] for n in sorted(self._by_name))


_REGISTRY: EventRegistry | None = None


def get_registry() -> EventRegistry:
    """Return the process-wide event registry (lazy-loads catalog)."""
    global _REGISTRY
    if _REGISTRY is None:
        from agentcore.observability.catalog import EVENTS

        _REGISTRY = MapEventRegistry(EVENTS)
    return _REGISTRY


def reset_registry_for_tests(registry: EventRegistry | None = None) -> None:
    """Replace or clear the process registry (tests only)."""
    global _REGISTRY
    _REGISTRY = registry


def _strict_mode(*, debug: bool) -> bool:
    """Strict = raise on unknown events. Env wins; else debug defaults to warn-only."""
    raw = os.environ.get("LOG_EVENT_REGISTRY_STRICT", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return False  # debug warns; never raise unless env opts in


def check_event_registered(
    name: str,
    *,
    debug: bool | None = None,
    registry: EventRegistry | None = None,
) -> None:
    """Validate ``name`` against the registry.

    - production (``debug=False``): no-op (loose)
    - debug: ``warnings.warn``; if ``LOG_EVENT_REGISTRY_STRICT`` → raise
    """
    if not isinstance(name, str) or "." not in name:
        return
    reg = registry if registry is not None else get_registry()
    if name in reg:
        return
    if debug is None:
        try:
            from agentcore.config import settings

            debug = bool(settings.debug)
        except Exception:  # noqa: BLE001 — never break emit path on settings load
            debug = False
    if not debug:
        return
    if _strict_mode(debug=debug):
        raise UnregisteredLogEventError(
            f"unregistered log event {name!r}; add it to "
            "agentcore.observability.catalog (uv run python "
            "scripts/sync_log_event_registry.py)"
        )
    warnings.warn(
        f"unregistered log event: {name}",
        UnregisteredLogEventWarning,
        stacklevel=3,
    )


def registry_processor(
    logger: object,  # noqa: ARG001 — structlog signature
    method_name: str,  # noqa: ARG001
    event_dict: dict,
) -> dict:
    """Structlog processor: check ``event`` against the registry (dev warn / prod loose)."""
    event = event_dict.get("event")
    if isinstance(event, str):
        check_event_registered(event)
    return event_dict
