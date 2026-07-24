"""Unit tests for capability-pack listing gate → runtime registry."""

from __future__ import annotations

import pytest

from agentcore.config import settings
from agentcore.runtime.capability_packs import (
    LEGAL_PACK_ID,
    enabled_packs,
    listed_packs,
)
from agentcore.runtime.legal_skills import LEGAL_SKILLS
from agentcore.runtime.skills import build_system_skill_registry


@pytest.fixture(autouse=True)
def _restore_legal_gate():
    """Keep the process-level listing gate off unless a test flips it."""
    previous = settings.legal_vertical_enabled
    settings.legal_vertical_enabled = False
    yield
    settings.legal_vertical_enabled = previous


def test_listed_packs_empty_when_gate_off():
    assert listed_packs() == []
    assert enabled_packs() == frozenset()


def test_listed_packs_includes_legal_when_gate_on():
    settings.legal_vertical_enabled = True
    packs = listed_packs()
    assert [p.id for p in packs] == [LEGAL_PACK_ID]
    assert enabled_packs() == frozenset({LEGAL_PACK_ID})


def test_registry_omits_legal_when_gate_off():
    reg = build_system_skill_registry(enabled_packs=enabled_packs())
    assert reg.get("legal_answer_brief") is None


def test_registry_includes_legal_when_gate_on():
    settings.legal_vertical_enabled = True
    reg = build_system_skill_registry(enabled_packs=enabled_packs())
    assert {s.name for s in LEGAL_SKILLS} <= {s.name for s in reg.list_all()}
