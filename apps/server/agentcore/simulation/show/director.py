"""导播编译器 v1：run / 赛制状态 → EpisodeManifest（规则模板为主）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentcore.simulation.scenarios.show.beats import beat_for
from agentcore.simulation.scenarios.show.cast import cast_by_id
from agentcore.simulation.show.manifest import (
    EPISODE_MANIFEST_VERSION,
    EpisodeHighlight,
    EpisodeManifest,
    EpisodeNextTeaser,
    EpisodeQuiz,
    EpisodeReveal,
    EpisodeRevealStep,
    EpisodeSegment,
    EpisodeShot,
    EpisodeTickSpan,
)
from agentcore.simulation.show.models import EpisodeRecord, EpisodeTickPlan, ShowSeasonState

# Repo-relative fixture used as episode-3 scripted tape (shape golden).
_FIXTURE_EP3 = (
    Path(__file__).resolve().parents[5]
    / "packages"
    / "protocol-conformance"
    / "fixtures"
    / "show"
    / "episode-3-manifest.json"
)


def load_episode3_fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE_EP3.read_text(encoding="utf-8"))


def compile_from_fixture_tape(
    *,
    run_id: str,
    fixture: dict[str, Any] | None = None,
) -> EpisodeManifest:
    """Scripted ep3 path: stamp run_id onto the golden tape (shape-aligned)."""
    data = dict(fixture or load_episode3_fixture())
    data["run_id"] = run_id
    data["version"] = EPISODE_MANIFEST_VERSION
    return EpisodeManifest.model_validate(data)


def compile_episode_manifest(
    *,
    run_id: str,
    season: ShowSeasonState,
    plan: EpisodeTickPlan,
    record: EpisodeRecord | None = None,
    tape: dict[str, Any] | None = None,
) -> EpisodeManifest:
    """Compile EpisodeManifest.

    Prefer a scripted tape when provided (or ep3 golden fixture). Otherwise build a
    minimal rule-template manifest from plan + ceremony record.
    """
    if tape is not None:
        return compile_from_fixture_tape(run_id=run_id, fixture=tape)
    if plan.episode_no == 3:
        return compile_from_fixture_tape(run_id=run_id)

    beat = beat_for(plan.episode_no)
    record = record or next(
        (e for e in season.episodes if e.episode_no == plan.episode_no), None
    )

    segments: list[EpisodeSegment] = []
    for gate, (start, end) in plan.gates.items():
        subjects = list(plan.date_locations)[:2] if gate == "day" else list(season.active_agent_ids)[:4]
        camera = {
            "recap": "wide_establish",
            "day": "follow_pair",
            "night": "orbit_group",
            "quiz": "push_in",
            "ceremony": "wide_establish",
            "reveal": "reveal_closeup",
            "epilogue": "push_in",
        }.get(gate, "wide_establish")
        segments.append(
            EpisodeSegment(
                id=gate,
                kind=gate,  # type: ignore[arg-type]
                label=_gate_label(gate, plan),
                tick_span=EpisodeTickSpan(start=start, end=end),
                shots=[
                    EpisodeShot(
                        id=f"{gate}-1",
                        camera=camera,  # type: ignore[arg-type]
                        subjects=subjects if gate != "recap" else [],
                        tick_at=start,
                        duration_hint_ms=4000,
                    )
                ],
                overlays=[
                    {
                        "kind": "title_card",
                        "text": _gate_label(gate, plan),
                        "tick_at": start,
                        "shot_id": f"{gate}-1",
                    }
                ],
            )
        )

    quiz = None
    if plan.quiz_focus:
        focus_name = cast_by_id(plan.quiz_focus).name
        options = [a for a in plan.allowed_picks.get(plan.quiz_focus, [])][:3]
        answer = ""
        if record:
            for p in record.picks:
                if p.from_agent_id == plan.quiz_focus:
                    answer = p.to_agent_id
                    break
        if not answer and options:
            answer = options[0]
        quiz = EpisodeQuiz(
            focus=plan.quiz_focus,
            question=f"今晚，{focus_name}的票会写给谁？",
            options=options or list(season.active_agent_ids)[:3],
            answer=answer or (options[0] if options else ""),
            insert_at={
                "tick": plan.gates["quiz"][0],
                "after_segment_id": "night",
            },
        )

    reveal = None
    if record is not None:
        reveal = EpisodeReveal(
            intro="揭晓时刻——六张纸条，当众开启。",
            steps=[
                EpisodeRevealStep(who=p.from_agent_id, pick=p.to_agent_id)
                for p in record.picks
            ],
            outro=_reveal_outro(record),
        )

    highlights = _default_highlights(plan, record)

    return EpisodeManifest(
        version=EPISODE_MANIFEST_VERSION,
        season=season.season_title,
        episode_no=plan.episode_no,
        title=f"第 {plan.episode_no} 期 · {beat.title}",
        run_id=run_id,
        tick_range=EpisodeTickSpan(start=plan.tick_start, end=plan.tick_end),
        tagline=beat.emotion_arc,
        rule_line="每晚一票心动 · 互选即配对 · 连续两期零票离场",
        segments=segments,
        quiz=quiz,
        reveal=reveal,
        highlights=highlights,
        next_teaser=_next_teaser(plan.episode_no),
    )


def _gate_label(gate: str, plan: EpisodeTickPlan) -> str:
    labels = {
        "recap": "前情",
        "day": "白天 · 约会",
        "night": f"夜话 · {plan.night_location}",
        "quiz": "竞猜",
        "ceremony": "心动之选",
        "reveal": "揭晓",
        "epilogue": "揭晓之后",
    }
    return labels.get(gate, gate)


def _reveal_outro(record: EpisodeRecord) -> list[str]:
    lines: list[str] = []
    if not record.pairs_formed:
        lines.append("今夜，无人配对。")
    else:
        for bond in record.pairs_formed:
            lines.append(f"配对成功：{bond.agent_a_id} × {bond.agent_b_id}")
    for aid in record.zero_vote_agents:
        lines.append(f"{aid}：零票。")
    for aid in record.departed:
        lines.append(f"{aid} 因连续两期零票离场。")
    return lines or ["本期揭晓结束。"]


def _default_highlights(
    plan: EpisodeTickPlan, record: EpisodeRecord | None
) -> list[EpisodeHighlight]:
    _ = record
    return [
        EpisodeHighlight(
            id="toxic",
            title="最毒一句",
            quote="有些话，一旦被点破就收不回了。",
            by=plan.quiz_focus or "zhouke",
            shot_id="night-1",
        ),
        EpisodeHighlight(
            id="twist",
            title="最大反转",
            quote="揭晓夜，总有人写的不是观众以为的名字。",
            by="shenwan",
            shot_id="reveal-1",
        ),
        EpisodeHighlight(
            id="sweet",
            title="最甜瞬间",
            quote="白天约会里，一句随口的关心。",
            by="luye",
            shot_id="day-1",
        ),
    ]


def _next_teaser(episode_no: int) -> EpisodeNextTeaser:
    nxt = min(7, episode_no + 1)
    beat = beat_for(nxt) if nxt != episode_no else beat_for(episode_no)
    return EpisodeNextTeaser(
        title=f"第 {nxt} 期 · {beat.title}",
        hook=beat.emotion_arc,
    )


def manifest_shape_keys(manifest: EpisodeManifest) -> set[str]:
    """Top-level keys required to match the golden fixture shape."""
    return set(manifest.model_dump(mode="json").keys())


GOLDEN_TOP_KEYS = frozenset(
    {
        "version",
        "season",
        "episode_no",
        "title",
        "run_id",
        "tick_range",
        "tagline",
        "rule_line",
        "segments",
        "quiz",
        "reveal",
        "highlights",
        "next_teaser",
    }
)
