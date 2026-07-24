"""Preset injectable world event templates (BE-22)."""

from __future__ import annotations

from typing import Any

from agentcore.simulation.world.events.models import (
    PresetEventType,
    WorldEvent,
    WorldEventKind,
)


def build_preset_event(
    event_type: PresetEventType | str,
    *,
    tick: int,
    payload: dict[str, Any] | None = None,
) -> WorldEvent:
    """Map a preset or custom inject type to a ``WorldEvent``."""
    extra = dict(payload or {})
    if event_type == PresetEventType.PRICE_SURGE or event_type == "price_surge":
        multiplier = float(extra.pop("multiplier", 1.5))
        return WorldEvent(
            kind=WorldEventKind.USER_INJECT,
            event_type="price_surge",
            title="市场物价上涨",
            description=f"全镇物价上涨，交易价格约为平时的 {multiplier:.1f} 倍。",
            payload={"multiplier": multiplier, **extra},
            tick_started=tick,
            duration_ticks=int(extra.pop("duration_ticks", 3)),
            source="god_mode",
        )
    if event_type == PresetEventType.STORM or event_type == "storm":
        return WorldEvent(
            kind=WorldEventKind.USER_INJECT,
            event_type="storm",
            title="暴风雨来袭",
            description="狂风暴雨，居民普遍倾向回家避险，户外活动减少。",
            payload=extra,
            tick_started=tick,
            duration_ticks=int(extra.pop("duration_ticks", 2)),
            source="god_mode",
        )
    if event_type == PresetEventType.FESTIVAL or event_type == "festival":
        return WorldEvent(
            kind=WorldEventKind.USER_INJECT,
            event_type="festival",
            title="节日庆典",
            description="广场举办庆典，人潮聚集，气氛欢快，居民情绪提升。",
            payload=extra,
            tick_started=tick,
            duration_ticks=int(extra.pop("duration_ticks", 4)),
            source="god_mode",
        )
    if event_type == PresetEventType.ANNOUNCEMENT or event_type == "announcement":
        motion = str(extra.pop("motion", "是否同意下周举办镇民大会？")).strip()
        return WorldEvent(
            kind=WorldEventKind.USER_INJECT,
            event_type="announcement",
            title="镇长发布公告",
            description=f"镇政厅发布议题：{motion}",
            payload={"motion": motion, **extra},
            tick_started=tick,
            duration_ticks=1,
            source="god_mode",
        )
    # custom
    title = str(extra.pop("title", "自定义事件")).strip() or "自定义事件"
    description = str(extra.pop("description", "")).strip() or title
    return WorldEvent(
        kind=WorldEventKind.USER_INJECT,
        event_type=str(extra.pop("event_type", "custom")),
        title=title,
        description=description,
        payload=extra,
        tick_started=tick,
        duration_ticks=int(extra.pop("duration_ticks", 1)),
        source="god_mode",
    )
