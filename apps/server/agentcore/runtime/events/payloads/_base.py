"""SSE payload wire-model base + codegen field markers (事件契约单源).

These pydantic models are the DESCRIPTIVE single source for SSE event payload
shapes: the factories in ``runtime/events/*.py`` remain the only construction
path (plain dicts on the hot path), while ``scripts/dump_sse_payload_types.py``
renders these models into ``packages/contract-types/src/events.generated.ts``
and ``tests/test_sse_payload_models.py`` validates real factory output (the
conformance vectors) against them.

Field conventions (the generator mirrors these 1:1):

- ``x: T``                     -> required, non-null        -> ``x: T``
- ``x: T | None``              -> required, nullable        -> ``x: T | null``
- ``x: T | None = None``       -> optional, nullable        -> ``x?: T | null``
- ``x: T = <default>``         -> optional (server default) -> ``x?: T``
- ``x: T | None = absent()``   -> optional, ABSENT when unset -> ``x?: T`` (no null)

Per-field escape hatch: ``Field(json_schema_extra={"ts_type": "Name"})`` forces
the emitted TS type text (used for opaque aliases like ``ToolDisplay``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WirePayload(BaseModel):
    """Base for SSE payload wire models — unknown keys are contract drift, so forbid."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def absent(description: str | None = None, *, ts_type: str | None = None) -> Any:
    """A field that is ABSENT from the wire dict when unset (TS ``field?: T``, no null)."""
    extra: dict[str, Any] = {"ts": "absent"}
    if ts_type:
        extra["ts_type"] = ts_type
    return Field(default=None, description=description, json_schema_extra=extra)


# ── TS export specs (consumed by scripts/dump_sse_payload_types.py) ────────────


@dataclass(frozen=True)
class TsAlias:
    """``export type Name = "a" | "b";`` from a ``Literal[...]`` alias or a StrEnum."""

    name: str
    obj: Any
    doc: str = ""


@dataclass(frozen=True)
class TsInterface:
    """``export interface Name { ... }`` from a pydantic model.

    ``render_raw`` overrides the whole right-hand side (``export type Name = <raw>;``)
    while keeping the model registered for validation (e.g. ``Record<string, never>``).
    ``force_required`` drops the ``?`` for fields that carry a Python-side default but
    are ALWAYS present on the wire (e.g. reused production models emitted via
    ``model_dump()``).
    """

    model: type[BaseModel]
    name: str = ""
    extends: type[BaseModel] | None = None
    force_required: frozenset[str] = frozenset()
    render_raw: str = ""
    doc: str = ""

    @property
    def ts_name(self) -> str:
        return self.name or self.model.__name__


@dataclass(frozen=True)
class TsInlineUnion:
    """``export type Name = | {...} | {...};`` — members rendered as inline object
    literals (their Python model names are NOT exported)."""

    name: str
    members: tuple[type[BaseModel], ...]
    doc: str = ""


@dataclass(frozen=True)
class TsRaw:
    """``export type Name = <ts>;`` — verbatim escape hatch (no backing model)."""

    name: str
    ts: str
    doc: str = ""


TsExport = TsAlias | TsInterface | TsInlineUnion | TsRaw
