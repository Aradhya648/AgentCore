"""Validate conformance vector + factory payloads against wire models."""

from __future__ import annotations

import pytest

from agentcore.conformance.vectors import VECTORS
from agentcore.runtime.events.payloads import EVENT_PAYLOAD_MODELS
from agentcore.runtime.events.types import EventType


@pytest.mark.parametrize("vector_name", sorted(VECTORS))
def test_conformance_vector_payloads_match_models(vector_name: str) -> None:
    _description, builder = VECTORS[vector_name]
    for event in builder():
        model = EVENT_PAYLOAD_MODELS.get(event.type)
        assert model is not None, f"{vector_name}: no payload model for {event.type!r}"
        model.model_validate(event.payload)


def test_every_event_type_has_payload_model() -> None:
    missing = [e for e in EventType if e not in EVENT_PAYLOAD_MODELS]
    assert not missing, f"EventType values missing payload models: {missing}"
