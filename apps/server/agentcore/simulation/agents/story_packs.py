"""Load demo story packs from packaged JSON (canonical → gen:story-packs).

Runtime data ships inside the ``agentcore`` wheel under
``agentcore/simulation/data/demo-story-packs.json``. Edit the SoT at
``packages/town-story-packs/demo-story-packs.json`` and run
``pnpm gen:story-packs``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal, cast

Speaker = Literal["initiator", "target", "mediator"]

_SPEAKER_MAP: dict[str, Speaker] = {
    "a": "initiator",
    "b": "target",
    "m": "mediator",
    "initiator": "initiator",
    "target": "target",
    "mediator": "mediator",
}

DEMO_PACK_PRICE_SURGE = "price_surge"
DEMO_PACK_FESTIVAL = "festival"
DEMO_PACK_TOWN_HALL = "town_hall"
DEMO_PACK_IDS = (DEMO_PACK_PRICE_SURGE, DEMO_PACK_FESTIVAL, DEMO_PACK_TOWN_HALL)

_DATA_RESOURCE = "demo-story-packs.json"


@dataclass(frozen=True)
class TradeSpec:
    item: str
    qty: int
    base_price: float


@dataclass(frozen=True)
class StoryBeat:
    """One demo-pulse beat in a scripted story pack."""

    kind: Literal["conversation", "trade", "vote"]
    lines: tuple[tuple[Speaker, str], ...]
    mood_initiator: float
    mood_target: float
    relation: float
    summary_template: str
    trade: TradeSpec | None = None
    world_event_blurb: str | None = None
    vote_motion: str | None = None
    include_mediator: bool = False
    location: str | None = None


@dataclass(frozen=True)
class StoryPack:
    pack_id: str
    world_presets: tuple[str, ...]
    beats: tuple[StoryBeat, ...]


def normalize_demo_pack(pack: str | None) -> str:
    """Normalize pack id; unknown → price_surge (default 涨价风波)."""
    if not pack:
        return DEMO_PACK_PRICE_SURGE
    key = pack.strip().lower()
    if key in DEMO_PACK_IDS:
        return key
    return DEMO_PACK_PRICE_SURGE


def _map_speaker(raw: str) -> Speaker:
    key = (raw or "a").strip().lower()
    return _SPEAKER_MAP.get(key, "initiator")


def _parse_beat(raw: dict[str, Any]) -> StoryBeat:
    kind = cast(Literal["conversation", "trade", "vote"], raw.get("kind") or "conversation")
    lines_raw = raw.get("lines") or []
    lines: list[tuple[Speaker, str]] = []
    for line in lines_raw:
        if not isinstance(line, dict):
            continue
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        lines.append((_map_speaker(str(line.get("speaker") or "a")), text))

    trade_raw = raw.get("trade")
    trade: TradeSpec | None = None
    if isinstance(trade_raw, dict) and trade_raw.get("item"):
        trade = TradeSpec(
            item=str(trade_raw["item"]),
            qty=int(trade_raw.get("qty") or 1),
            base_price=float(trade_raw.get("base_price") or 0.0),
        )

    include = raw.get("include_mediator")
    if include is None:
        include = any(speaker == "mediator" for speaker, _ in lines)

    world_event_blurb = raw.get("world_event_blurb")
    if world_event_blurb is not None:
        world_event_blurb = str(world_event_blurb).strip() or None

    vote_motion = raw.get("vote_motion")
    if vote_motion is not None:
        vote_motion = str(vote_motion).strip() or None

    location = raw.get("location")
    if location is not None:
        location = str(location).strip() or None

    summary = str(raw.get("summary_template") or "").strip()
    if not summary:
        raise ValueError(f"story beat missing summary_template (kind={kind})")

    return StoryBeat(
        kind=kind,
        lines=tuple(lines),
        mood_initiator=float(raw.get("mood_initiator") or 0.0),
        mood_target=float(raw.get("mood_target") or 0.0),
        relation=float(raw.get("relation") or 0.0),
        summary_template=summary,
        trade=trade,
        world_event_blurb=world_event_blurb,
        vote_motion=vote_motion,
        include_mediator=bool(include),
        location=location,
    )


def _parse_pack(raw: dict[str, Any]) -> StoryPack:
    pack_id = normalize_demo_pack(str(raw.get("id") or ""))
    presets_raw = raw.get("world_presets") or []
    presets = tuple(str(p) for p in presets_raw if p)
    beats_raw = raw.get("beats") or []
    beats = tuple(_parse_beat(b) for b in beats_raw if isinstance(b, dict))
    if not beats:
        raise ValueError(f"story pack {pack_id!r} has no beats")
    if not presets:
        raise ValueError(f"story pack {pack_id!r} has no world_presets")
    return StoryPack(pack_id=pack_id, world_presets=presets, beats=beats)


@lru_cache(maxsize=1)
def load_story_packs() -> dict[str, StoryPack]:
    """Load all packs from packaged JSON (fail-closed if missing/malformed)."""
    resource = files("agentcore.simulation.data").joinpath(_DATA_RESOURCE)
    raw_text = resource.read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    packs_raw = payload.get("packs")
    if not isinstance(packs_raw, list) or not packs_raw:
        raise ValueError(f"{_DATA_RESOURCE}: missing packs[]")
    by_id: dict[str, StoryPack] = {}
    for item in packs_raw:
        if not isinstance(item, dict):
            continue
        pack = _parse_pack(item)
        by_id[pack.pack_id] = pack
    for required in DEMO_PACK_IDS:
        if required not in by_id:
            raise ValueError(f"{_DATA_RESOURCE}: missing required pack {required!r}")
    return by_id


def beats_for_pack(pack: str) -> tuple[StoryBeat, ...]:
    resolved = normalize_demo_pack(pack)
    return load_story_packs()[resolved].beats


def presets_for_pack(pack: str) -> tuple[str, ...]:
    resolved = normalize_demo_pack(pack)
    return load_story_packs()[resolved].world_presets


def reset_story_pack_cache() -> None:
    """Test helper: clear lru_cache after swapping packaged JSON."""
    load_story_packs.cache_clear()
