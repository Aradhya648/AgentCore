"""Integration: deployment-gated packs on GET /v1/capabilities."""

from __future__ import annotations

from agentcore.config import settings
from tests.integration.conftest import register_and_login


async def test_capabilities_packs_empty_when_gate_off(client, make_invite):
    code = await make_invite("INV-PACK-1")
    await register_and_login(client, code, "packempty")
    body = (await client.get("/v1/capabilities")).json()
    assert body["packs"] == []
    assert "legal_answer_brief" not in {s["name"] for s in body["skills"]}


async def test_gate_on_lists_pack_and_registers_skills(client, make_invite, monkeypatch):
    monkeypatch.setattr(settings, "legal_vertical_enabled", True)
    code = await make_invite("INV-PACK-2")
    await register_and_login(client, code, "packon")

    body = (await client.get("/v1/capabilities")).json()
    packs = {p["id"]: p for p in body["packs"]}
    assert "legal" in packs
    assert "enabled" not in packs["legal"]
    assert packs["legal"]["skills"]
    skill_names = {s["name"] for s in body["skills"]}
    assert "legal_answer_brief" in skill_names
    assert "legal_case_analysis" in skill_names
