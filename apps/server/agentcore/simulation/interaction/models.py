"""Pydantic models for M3 structured interactions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

InteractionKind = Literal["conversation", "trade", "vote", "heart_pick"]
InteractionStatus = Literal["completed", "rejected", "failed", "cancelled"]


class InteractionRequest(BaseModel):
    """One interaction intent queued for the current tick."""

    request_id: str
    kind: InteractionKind
    initiator_id: str
    target_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class InteractionTranscriptLine(BaseModel):
    speaker_id: str
    speaker_name: str
    text: str
    round: int = 0


class InteractionStateChange(BaseModel):
    """Summary of world mutations applied by an interaction."""

    mood_deltas: dict[str, float] = Field(default_factory=dict)
    relation_deltas: list[tuple[str, str, float]] = Field(default_factory=list)
    money_transfers: list[dict[str, Any]] = Field(default_factory=list)
    inventory_transfers: list[dict[str, Any]] = Field(default_factory=list)
    governance: dict[str, Any] = Field(default_factory=dict)


class InteractionResult(BaseModel):
    request_id: str
    kind: InteractionKind
    status: InteractionStatus
    initiator_id: str
    target_id: str | None = None
    summary: str
    transcript: list[InteractionTranscriptLine] = Field(default_factory=list)
    state_changes: InteractionStateChange = Field(default_factory=InteractionStateChange)
    detail: str = ""


class SimInteractionPayload(BaseModel):
    """Structured interaction result on ``sim.interaction``."""

    run_id: str
    tick: int
    interaction: InteractionResult
