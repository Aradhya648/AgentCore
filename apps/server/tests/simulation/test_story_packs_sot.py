"""Story-pack single-SoT: canonical ↔ materialized outputs ↔ backend loader."""

from __future__ import annotations

import json
from pathlib import Path

from agentcore.simulation.agents.story_packs import (
    DEMO_PACK_IDS,
    beats_for_pack,
    load_story_packs,
    normalize_demo_pack,
    presets_for_pack,
)

_ROOT = Path(__file__).resolve().parents[4]
_CANONICAL = _ROOT / "packages" / "town-story-packs" / "demo-story-packs.json"
_UNITY = (
    _ROOT
    / "apps"
    / "town"
    / "Assets"
    / "StreamingAssets"
    / "Fixtures"
    / "demo-story-packs.json"
)
_BACKEND = (
    _ROOT
    / "apps"
    / "server"
    / "agentcore"
    / "simulation"
    / "data"
    / "demo-story-packs.json"
)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_story_pack_materialized_outputs_match_canonical() -> None:
    """Fail-closed drift gate: edit SoT then ``pnpm gen:story-packs``."""
    canonical = _load(_CANONICAL)
    assert _load(_UNITY) == canonical
    assert _load(_BACKEND) == canonical


def test_story_pack_loader_reads_packaged_data() -> None:
    packs = load_story_packs()
    assert set(packs) >= set(DEMO_PACK_IDS)

    surge = packs["price_surge"]
    assert len(surge.beats) == 9
    assert surge.world_presets == ("price_surge", "storm", "festival")
    assert surge.beats[0].kind == "conversation"
    assert surge.beats[0].lines[0][0] == "initiator"
    assert "试探" in surge.beats[0].summary_template
    assert surge.beats[1].trade is not None
    assert surge.beats[1].trade.item == "日用品"
    assert surge.beats[1].world_event_blurb
    assert surge.beats[4].include_mediator is True
    assert surge.beats[5].kind == "vote"
    assert surge.beats[5].vote_motion

    fest = packs["festival"]
    assert len(fest.beats) == 6
    assert fest.world_presets == ("festival", "festival", "festival")
    assert "节日庆典" in fest.beats[0].summary_template

    hall = packs["town_hall"]
    assert len(hall.beats) == 6
    assert hall.world_presets[0] == "announcement"
    assert hall.beats[3].kind == "vote"


def test_beats_and_presets_helpers_match_loader() -> None:
    assert beats_for_pack("Festival") is load_story_packs()["festival"].beats
    assert presets_for_pack(None) == load_story_packs()["price_surge"].world_presets
    assert normalize_demo_pack("town_hall") == "town_hall"
