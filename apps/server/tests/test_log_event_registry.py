"""Unit tests for the product-AI log event registry."""

from __future__ import annotations

import warnings

import pytest

from agentcore.observability.events import (
    EventSpec,
    FieldType,
    MapEventRegistry,
    UnregisteredLogEventError,
    UnregisteredLogEventWarning,
    check_event_registered,
    get_registry,
    registry_processor,
    reset_registry_for_tests,
)


@pytest.fixture(autouse=True)
def _restore_registry():
    yield
    reset_registry_for_tests(None)


def test_catalog_covers_key_runtime_events():
    names = get_registry().names()
    for required in (
        "chat.turn_start",
        "chat.turn_complete",
        "delegate.started",
        "tool.execute_end",
        "llm.call",
        "engine.loop_nudge",
        "cost.recorded",
        "pipeline.error",
        "http.unhandled_error",
        "approval.sandbox_auto_pass",
        "firehose.backpressure_drop",
    ):
        assert required in names, required
    assert len(names) >= 100


def test_event_spec_rejects_bare_name():
    with pytest.raises(ValueError, match="component.action"):
        EventSpec(name="bare")


def test_check_unregistered_prod_loose():
    reg = MapEventRegistry([EventSpec(name="chat.turn_start")])
    # production: silent
    check_event_registered("totally.unknown", debug=False, registry=reg)


def test_check_unregistered_dev_warns():
    reg = MapEventRegistry([EventSpec(name="chat.turn_start")])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        check_event_registered("totally.unknown", debug=True, registry=reg)
    assert any(issubclass(w.category, UnregisteredLogEventWarning) for w in caught)


def test_check_unregistered_strict_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOG_EVENT_REGISTRY_STRICT", "1")
    reg = MapEventRegistry([EventSpec(name="chat.turn_start")])
    with pytest.raises(UnregisteredLogEventError):
        check_event_registered("totally.unknown", debug=True, registry=reg)


def test_registry_processor_passthrough():
    reg = MapEventRegistry(
        [EventSpec(name="chat.turn_start", fields={"preview": FieldType("str")})]
    )
    reset_registry_for_tests(reg)
    out = registry_processor(None, "info", {"event": "chat.turn_start", "preview": "hi"})
    assert out["event"] == "chat.turn_start"


def test_registry_processor_warns_unregistered_in_debug(monkeypatch: pytest.MonkeyPatch):
    # The processor chain is the ONLY validation path (no separate emit API):
    # unknown names must warn in dev yet still pass the event dict through.
    from agentcore.config import settings

    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.delenv("LOG_EVENT_REGISTRY_STRICT", raising=False)
    reset_registry_for_tests(MapEventRegistry([EventSpec(name="chat.turn_start")]))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = registry_processor(None, "info", {"event": "totally.unknown", "k": 1})
    assert out == {"event": "totally.unknown", "k": 1}  # never blocks the emit
    assert any(issubclass(w.category, UnregisteredLogEventWarning) for w in caught)


def test_duplicate_registration_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        MapEventRegistry(
            [EventSpec(name="chat.turn_start"), EventSpec(name="chat.turn_start")]
        )
