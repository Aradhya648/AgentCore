"""CEO seed_notes + team_brief (共享便签 Phase 2)."""

from agentcore.runtime.delegate.seed_notes import (
    CEO_SEED_RUN_ID,
    MAX_SEED_NOTES,
    MAX_TEAM_BRIEF_CHARS,
    parse_seed_notes,
    parse_team_brief,
    resolve_coordination,
    seed_note_wall,
)
from agentcore.runtime.events import EventSink, EventType
from agentcore.runtime.runs.notewall import NOTE_KIND_DECISION, NOTE_KIND_HEADS_UP, NoteWall


def test_parse_seed_notes_accepts_valid_items():
    notes, err = parse_seed_notes(
        [
            {"kind": "decision", "text": "  受众：初学者  "},
            {"text": "别写太长"},
        ]
    )
    assert err is None
    assert notes == [
        {"kind": NOTE_KIND_DECISION, "text": "受众：初学者"},
        {"kind": NOTE_KIND_HEADS_UP, "text": "别写太长"},
    ]


def test_parse_seed_notes_rejects_invalid():
    assert parse_seed_notes("x")[1] is not None
    too_many = [{"text": f"n{i}"} for i in range(MAX_SEED_NOTES + 1)]
    assert "最多" in (parse_seed_notes(too_many)[1] or "")
    assert "非空" in (parse_seed_notes([{"text": "  "}])[1] or "")


def test_parse_team_brief_trims_and_caps():
    brief, err = parse_team_brief("  跨波共识\n第二行  ")
    assert err is None and brief == "跨波共识\n第二行"
    long_text = "字" * (MAX_TEAM_BRIEF_CHARS + 50)
    capped, err = parse_team_brief(long_text)
    assert err is None and capped is not None and len(capped) <= MAX_TEAM_BRIEF_CHARS


def test_parse_team_brief_rejects_non_string():
    assert parse_team_brief(42)[1] is not None
    assert parse_team_brief("   ")[1] is not None


def test_seed_note_wall_posts_and_emits_ceo_source():
    wall = NoteWall()
    sink = EventSink()
    count = seed_note_wall(
        wall,
        [{"kind": "decision", "text": "方向：科普向"}],
        sink=sink,
        execution_id="exec-1",
    )
    assert count == 1
    assert len(wall._notes) == 1  # noqa: SLF001
    note = wall._notes[0]  # noqa: SLF001
    assert note.run_id == CEO_SEED_RUN_ID
    events = [e for e in sink._history if e.type == EventType.TEAM_NOTE_POSTED]  # noqa: SLF001
    assert len(events) == 1
    assert events[0].payload["source"] == "ceo"
    assert events[0].payload["text"] == "方向：科普向"


def test_ceo_seeds_visible_to_workers_via_new_for():
    wall = NoteWall()
    seed_note_wall(
        wall,
        [{"text": "共享验收维度"}],
        sink=EventSink(),
        execution_id="e",
    )
    fresh = wall.new_for("worker-run-1")
    assert [n.text for n in fresh] == ["共享验收维度"]
    assert fresh[0].run_id == CEO_SEED_RUN_ID


def test_resolve_coordination_defaults_none():
    assert (
        resolve_coordination(
            raw=None, complexity_hint="standard", seed_notes=None, team_brief=None
        )
        == "none"
    )


def test_resolve_coordination_explicit_wall():
    assert (
        resolve_coordination(
            raw="wall", complexity_hint="standard", seed_notes=None, team_brief=None
        )
        == "wall"
    )


def test_resolve_coordination_light_forces_none():
    assert (
        resolve_coordination(
            raw="wall",
            complexity_hint="light",
            seed_notes=[{"text": "x"}],
            team_brief="brief",
        )
        == "none"
    )


def test_resolve_coordination_seed_notes_upgrades_none():
    assert (
        resolve_coordination(
            raw="none",
            complexity_hint="standard",
            seed_notes=[{"text": "定了 X"}],
            team_brief=None,
        )
        == "wall"
    )


def test_resolve_coordination_team_brief_upgrades_none():
    assert (
        resolve_coordination(
            raw=None,
            complexity_hint="standard",
            seed_notes=None,
            team_brief="共享验收",
        )
        == "wall"
    )


def test_resolve_coordination_build_feature_playbook_defaults_wall():
    assert (
        resolve_coordination(
            raw=None,
            complexity_hint="standard",
            seed_notes=None,
            team_brief=None,
            playbook="build_feature",
        )
        == "wall"
    )
    # Explicit none is respected when there is no seed/brief upgrade.
    assert (
        resolve_coordination(
            raw="none",
            complexity_hint="standard",
            seed_notes=None,
            team_brief=None,
            playbook="build_feature",
        )
        == "none"
    )


def test_resolve_coordination_build_website_playbook_defaults_wall():
    assert (
        resolve_coordination(
            raw=None,
            complexity_hint="standard",
            seed_notes=None,
            team_brief=None,
            playbook="build_website",
        )
        == "wall"
    )
    assert (
        resolve_coordination(
            raw="none",
            complexity_hint="standard",
            seed_notes=None,
            team_brief=None,
            playbook="build_website",
        )
        == "none"
    )
