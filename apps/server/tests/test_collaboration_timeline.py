"""项目级协作时间线投影单测（批 D+ · 读时聚合，无 DB）。"""

from __future__ import annotations

from datetime import UTC, datetime

from agentcore.folders.collaboration_timeline import (
    extract_acts_from_journal,
    extract_dossier_refs,
    project_conversation_timeline,
)


def _ts(h: int = 0) -> str:
    return datetime(2026, 7, 19, h, 0, 0, tzinfo=UTC).isoformat()


def test_multi_session_multi_act_projection():
    """多幕：调研 → 辩论，host = 首个非 divert run_plan turn。"""
    entries = [
        {
            "turn_id": "turn-host",
            "kind": "run_plan",
            "ts": _ts(1),
            "payload": {
                "execution_id": "exec-1",
                "plan_type": "multi_agent",
                "act": {
                    "act_id": "act-1",
                    "kind": "multi_agent",
                    "title": "多视角调研",
                },
                "agents": [],
                "runs": [],
            },
        },
        {
            "turn_id": "turn-debate",
            "kind": "run_plan",
            "ts": _ts(2),
            "payload": {
                "execution_id": "exec-1",
                "plan_type": "debate",
                "host_message_id": "turn-host",
                "act": {
                    "act_id": "act-2",
                    "kind": "debate",
                    "title": "辩论对抗",
                },
                "agents": [],
                "runs": [],
            },
        },
    ]
    eid, host, acts = extract_acts_from_journal(entries)
    assert eid == "exec-1"
    assert host == "turn-host"
    assert [a.act_id for a in acts] == ["act-1", "act-2"]
    assert [a.title for a in acts] == ["多视角调研", "辩论对抗"]
    assert [a.kind for a in acts] == ["multi_agent", "debate"]


def test_legacy_single_act_compat():
    """旧单幕图无 act → 合成 act-1，kind = plan_type。"""
    entries = [
        {
            "turn_id": "t1",
            "kind": "run_plan",
            "ts": _ts(1),
            "payload": {
                "execution_id": "e-legacy",
                "plan_type": "debate",
                "agents": [],
                "runs": [],
            },
        }
    ]
    eid, host, acts = extract_acts_from_journal(entries)
    assert eid == "e-legacy"
    assert host == "t1"
    assert len(acts) == 1
    assert acts[0].act_id == "act-1"
    assert acts[0].kind == "debate"
    assert acts[0].title is None


def test_empty_journal_no_item():
    assert project_conversation_timeline(
        conversation_id="c1",
        title="空",
        updated_at=datetime(2026, 7, 19, tzinfo=UTC),
        entries=[],
    ) is None


def test_dossier_refs_from_inject_and_file_read():
    entries = [
        {
            "turn_id": "t1",
            "kind": "run_plan",
            "ts": _ts(1),
            "payload": {
                "execution_id": "e1",
                "plan_type": "debate",
                "act": {"act_id": "act-1", "kind": "debate", "title": "辩论对抗"},
                "agents": [],
                "runs": [],
            },
        },
        {
            "turn_id": "t1",
            "kind": "evidence_ledger",
            "ts": _ts(2),
            "payload": {
                "delta": [
                    {
                        "side_key": "dossier",
                        "dossier_path": "research/法律透镜报告.md",
                        "dossier_label": "法律",
                    },
                    {
                        "side_key": "moderator",
                        "dossier_path": "",
                    },
                ]
            },
        },
        {
            "turn_id": "t1",
            "kind": "tool_use_start",
            "ts": _ts(3),
            "payload": {
                "tool_name": "file_read",
                "arguments": {"path": "research/汇总与命题卡.md"},
            },
        },
        {
            "turn_id": "t1",
            "kind": "tool_use_start",
            "ts": _ts(4),
            "payload": {
                "tool_name": "file_read",
                "arguments": {"path": "debate/brief.md"},  # 非 research → 忽略
            },
        },
        {
            "turn_id": "t1",
            "kind": "tool_use_start",
            "ts": _ts(5),
            "payload": {
                "tool_name": "file_read",
                "arguments": {"path": "research/法律透镜报告.md"},  # 与 inject 合并
            },
        },
    ]
    refs = extract_dossier_refs(entries)
    by_path = {r.path: r.sources for r in refs}
    assert by_path["research/法律透镜报告.md"] == ["dossier_inject", "file_read"]
    assert by_path["research/汇总与命题卡.md"] == ["file_read"]
    assert "debate/brief.md" not in by_path


def test_latest_execution_wins_when_multiple():
    """同一会话多 execution 时取最新。"""
    entries = [
        {
            "turn_id": "old",
            "kind": "run_plan",
            "ts": _ts(1),
            "payload": {
                "execution_id": "exec-old",
                "plan_type": "multi_agent",
                "act": {"act_id": "act-1", "kind": "multi_agent", "title": "旧图"},
                "agents": [],
                "runs": [],
            },
        },
        {
            "turn_id": "new",
            "kind": "run_plan",
            "ts": _ts(5),
            "payload": {
                "execution_id": "exec-new",
                "plan_type": "debate",
                "act": {"act_id": "act-1", "kind": "debate", "title": "新辩论"},
                "agents": [],
                "runs": [],
            },
        },
    ]
    eid, host, acts = extract_acts_from_journal(entries)
    assert eid == "exec-new"
    assert host == "new"
    assert acts[0].title == "新辩论"


def test_project_item_includes_dossier_refs():
    entries = [
        {
            "turn_id": "t1",
            "kind": "run_plan",
            "ts": _ts(1),
            "payload": {
                "execution_id": "e1",
                "plan_type": "multi_agent",
                "act": {
                    "act_id": "act-1",
                    "kind": "multi_agent",
                    "title": "多视角调研",
                },
                "agents": [],
                "runs": [],
            },
        },
        {
            "turn_id": "t1",
            "kind": "evidence_ledger",
            "payload": {
                "entries": [
                    {
                        "side_key": "dossier",
                        "dossier_path": "research/品牌商业透镜报告.md",
                    }
                ]
            },
        },
    ]
    item = project_conversation_timeline(
        conversation_id="c-mlr",
        title="LV 案",
        updated_at=datetime(2026, 7, 19, tzinfo=UTC),
        entries=entries,
    )
    assert item is not None
    assert item.host_turn_id == "t1"
    assert item.acts[0].title == "多视角调研"
    assert item.dossier_refs[0].path == "research/品牌商业透镜报告.md"
    assert item.dossier_refs[0].sources == ["dossier_inject"]
