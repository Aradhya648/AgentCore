"""User workflow definition validate/expand + topology-lock unit tests."""

from __future__ import annotations

import pytest

from agentcore.runtime.delegate.supervised import apply_replan
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.constants import MAX_DELEGATION_TASKS
from agentcore.runtime.runs.plan import RunPlan
from agentcore.runtime.runs.playbooks import PLAYBOOKS, expand_playbook
from agentcore.runtime.runs.serialize import plan_from_json, plan_to_json
from agentcore.runtime.runs.types import RunSpec
from agentcore.workflows.definition import (
    WorkflowDefinitionError,
    expand_workflow_to_tasks,
    tasks_dropped_meta_keys,
    tasks_to_workflow_definition,
    validate_workflow_definition,
)
from agentcore.workflows.playbook_templates import (
    WORKFLOW_PLAYBOOK_IDS,
    PlaybookTemplateError,
    instantiate_from_playbook,
    list_playbook_templates,
    merge_playbook_slots,
)


def _qc_definition() -> dict:
    return {
        "nodes": [
            {
                "id": "research",
                "kind": "agent_step",
                "role": "研究员",
                "task": "调研现状",
                "deliverable": {"form": "notes"},
            },
            {"id": "gate1", "kind": "human_gate", "label": "审初稿"},
            {
                "id": "write",
                "kind": "agent_step",
                "role": "写手",
                "task": "根据调研写报告",
            },
        ],
        "edges": [
            {"from": "research", "to": "gate1"},
            {"from": "gate1", "to": "write"},
        ],
    }


def test_validate_ok():
    assert validate_workflow_definition(_qc_definition()) == []


def test_validate_allows_empty_draft():
    """Create/save may persist a blank canvas; run-time expand enforces agent_step."""
    assert validate_workflow_definition({"nodes": [], "edges": []}) == []
    assert validate_workflow_definition({"nodes": [], "edges": None}) == []


def test_expand_rejects_empty_draft():
    with pytest.raises(WorkflowDefinitionError, match="至少需要一个 agent_step"):
        expand_workflow_to_tasks({"nodes": [], "edges": []})


def test_validate_rejects_cycle():
    definition = {
        "nodes": [
            {"id": "a", "kind": "agent_step", "role": "A", "task": "a"},
            {"id": "b", "kind": "agent_step", "role": "B", "task": "b"},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    }
    errs = validate_workflow_definition(definition)
    assert any("环" in e for e in errs)


def test_validate_rejects_empty_agent_fields():
    definition = {
        "nodes": [{"id": "a", "kind": "agent_step", "role": " ", "task": ""}],
        "edges": [],
    }
    errs = validate_workflow_definition(definition)
    assert any("role" in e for e in errs)
    assert any("task" in e for e in errs)


def test_validate_rejects_over_limit():
    nodes = [
        {
            "id": f"n{i}",
            "kind": "agent_step",
            "role": "R",
            "task": f"t{i}",
        }
        for i in range(MAX_DELEGATION_TASKS + 1)
    ]
    errs = validate_workflow_definition({"nodes": nodes, "edges": []})
    assert any(str(MAX_DELEGATION_TASKS) in e for e in errs)


def test_expand_marks_checkpoint_and_deps():
    tasks = expand_workflow_to_tasks(_qc_definition())
    by_id = {t["id"]: t for t in tasks}
    assert set(by_id) == {"research", "write"}
    assert by_id["research"]["checkpoint_after"] is True
    assert "checkpoint_after" not in by_id["write"] or by_id["write"].get(
        "checkpoint_after"
    ) is not True
    assert by_id["write"]["depends_on"] == ["research"]
    assert by_id["research"]["role"] == "研究员"
    assert by_id["research"]["deliverable"] == {"form": "notes"}


def test_expand_builds_run_plan_golden():
    tasks = expand_workflow_to_tasks(_qc_definition())
    plan, errors = build_run_plan(tasks, id_prefix="wf")
    assert errors == []
    assert plan is not None
    assert len(plan.nodes) == 2
    research = plan.by_id("wf_research")
    write = plan.by_id("wf_write")
    assert research is not None and research.checkpoint_after is True
    assert write is not None
    assert write.depends_on == ["wf_research"]


def test_expand_invalid_raises():
    with pytest.raises(WorkflowDefinitionError):
        expand_workflow_to_tasks({"nodes": [], "edges": []})


def _structural_task(t: dict) -> dict:
    """Compare expand ↔ reverse without dropped meta keys."""
    out = {
        "id": t["id"],
        "role": t["role"],
        "task": t["task"],
    }
    if t.get("depends_on"):
        out["depends_on"] = list(t["depends_on"])
    if t.get("checkpoint_after") is True:
        out["checkpoint_after"] = True
    if isinstance(t.get("deliverable"), dict) and t["deliverable"]:
        out["deliverable"] = dict(t["deliverable"])
    return out


def test_tasks_to_definition_roundtrip_qc():
    """expand → tasks_to_definition → expand recovers structure (gate id may rename)."""
    tasks = expand_workflow_to_tasks(_qc_definition())
    definition = tasks_to_workflow_definition(tasks)
    kinds = {n["id"]: n["kind"] for n in definition["nodes"]}
    assert kinds["research"] == "agent_step"
    assert kinds["write"] == "agent_step"
    assert any(k.startswith("gate_after_") for k in kinds)
    assert kinds[next(k for k in kinds if k.startswith("gate_after_"))] == "human_gate"
    again = expand_workflow_to_tasks(definition)
    assert [_structural_task(t) for t in again] == [_structural_task(t) for t in tasks]


def test_tasks_to_definition_checkpoint_and_parallel_deps_golden():
    tasks = [
        {"id": "a", "role": "A", "task": "ta", "checkpoint_after": True},
        {"id": "b", "role": "B", "task": "tb"},
        {"id": "c", "role": "C", "task": "tc", "depends_on": ["a", "b"]},
    ]
    definition = tasks_to_workflow_definition(tasks)
    by_id = {n["id"]: n for n in definition["nodes"]}
    assert by_id["gate_after_a"]["kind"] == "human_gate"
    edge_set = {(e["from"], e["to"]) for e in definition["edges"]}
    assert ("a", "gate_after_a") in edge_set
    assert ("gate_after_a", "c") in edge_set
    assert ("b", "c") in edge_set
    assert ("a", "c") not in edge_set
    roundtrip = expand_workflow_to_tasks(definition)
    assert [_structural_task(t) for t in roundtrip] == [_structural_task(t) for t in tasks]


def test_tasks_to_definition_drops_tools_meta():
    tasks = [
        {
            "id": "x",
            "role": "R",
            "task": "do",
            "tools": ["file_read"],
            "max_rounds": 4,
            "timeout_ms": 1000,
        }
    ]
    assert tasks_dropped_meta_keys(tasks) == ["max_rounds", "timeout_ms", "tools"]
    definition = tasks_to_workflow_definition(tasks)
    assert "tools" not in definition["nodes"][0]
    again = expand_workflow_to_tasks(definition)
    assert "tools" not in again[0]
    assert again[0]["id"] == "x"


def test_playbook_template_catalog():
    items = list_playbook_templates()
    ids = [i.id for i in items]
    assert ids == list(WORKFLOW_PLAYBOOK_IDS)
    assert set(ids) <= set(PLAYBOOKS)
    for item in items:
        assert item.title
        assert item.primary_slots
        assert "不保留" in item.summary or "降级" in item.summary


def test_from_playbook_success_research_report():
    name, description, definition = instantiate_from_playbook(
        "research_report",
        {"topic": "量子计算"},
        name=None,
    )
    assert "调研报告" in name
    assert "量子计算" in name
    assert description and "research_report" in description
    tasks = expand_workflow_to_tasks(definition)
    by_id = {t["id"]: t for t in tasks}
    assert "outline" in by_id
    assert by_id["outline"].get("checkpoint_after") is True
    assert by_id["write"]["depends_on"] == ["outline"]
    # tools on review dropped from canvas
    assert "tools" not in by_id["review"]
    # PLAYBOOKS registry untouched
    assert "user_workflow" not in PLAYBOOKS
    assert all(pid in PLAYBOOKS for pid in WORKFLOW_PLAYBOOK_IDS)


def test_from_playbook_rejects_not_in_catalog():
    with pytest.raises(PlaybookTemplateError) as ei:
        merge_playbook_slots("repair_code", {"problem": "x", "verify": "pytest"})
    assert "暂未列入" in str(ei.value)

    with pytest.raises(PlaybookTemplateError) as ei2:
        instantiate_from_playbook("repair_code", {"problem": "x", "verify": "pytest"})
    assert "暂未列入" in str(ei2.value)


def test_from_playbook_rejects_unknown_and_missing_slot():
    with pytest.raises(PlaybookTemplateError) as ei:
        merge_playbook_slots("nope", {})
    assert "未知" in str(ei.value)

    with pytest.raises(PlaybookTemplateError) as ei2:
        merge_playbook_slots("research_report", {})
    assert "topic" in str(ei2.value)

    with pytest.raises(PlaybookTemplateError) as ei3:
        merge_playbook_slots("parallel_brief", {"topic": "T", "angles": []})
    assert "angles" in str(ei3.value)


def test_from_playbook_optional_name_and_defaults():
    name, _, definition = instantiate_from_playbook(
        "parallel_brief",
        {"topic": "量子计算", "angles": ["法律", "品牌"]},
        name="我的对齐流",
    )
    assert name == "我的对齐流"
    tasks = expand_workflow_to_tasks(definition)
    assert len(tasks) == 2
    assert tasks[0]["id"] == "brief_0"
    # Default optional checkpoint on research_report is applied via soft merge
    pb_tasks, err = expand_playbook("research_report", {"topic": "X"})
    assert err == []
    _, _, defn = instantiate_from_playbook("research_report", {"topic": "X"})
    round_tasks = expand_workflow_to_tasks(defn)
    assert [_structural_task(t) for t in round_tasks] == [
        _structural_task(t) for t in pb_tasks
    ]


def test_from_playbook_parallel_brief_coerces_angles_string():
    merged = merge_playbook_slots(
        "parallel_brief", {"topic": "T", "angles": "法律,品牌,舆情"}
    )
    assert merged["angles"] == ["法律", "品牌", "舆情"]
    name, _, definition = instantiate_from_playbook(
        "parallel_brief",
        {"topic": "议题", "angles": "甲、乙"},
    )
    assert "多角对齐摸底" in name
    assert "议题" in name
    tasks = expand_workflow_to_tasks(definition)
    assert len(tasks) == 2


def test_topology_lock_serializes():
    plan = RunPlan(
        nodes=[RunSpec(run_id="r1", role="A", task="a")],
        topology_lock=True,
        workflow_id="wf1",
        workflow_version=3,
    )
    raw = plan_to_json(plan)
    assert raw["topology_lock"] is True
    assert raw["workflow_id"] == "wf1"
    assert raw["workflow_version"] == 3
    restored = plan_from_json(raw)
    assert restored.topology_lock is True
    assert restored.workflow_id == "wf1"
    assert restored.workflow_version == 3


class _FakeTools:
    def list_all(self):
        return []


class _FakeDelegate:
    _tools = _FakeTools()
    _captain_run_id = "cap"
    _depth = 0
    _topology_lock = False


def test_topology_lock_blocks_replan_add_allows_steer():
    plan = RunPlan(
        nodes=[
            RunSpec(run_id="r1", role="A", task="done"),
            RunSpec(run_id="r2", role="B", task="pending", depends_on=["r1"]),
        ],
        topology_lock=True,
    )
    tool = _FakeDelegate()
    errors = apply_replan(
        tool,
        plan,
        completed={},
        binds=[],
        steers=[],
        adds=[{"role": "C", "task": "sneak"}],
    )
    assert errors
    assert any("拓扑锁" in e for e in errors)

    errors2 = apply_replan(
        tool,
        plan,
        completed={},
        binds=[],
        steers=[{"run_id": "r2", "note": "请按质检清单写"}],
        adds=[],
    )
    assert errors2 == []
    assert "请按质检清单写" in (plan.by_id("r2").steer or "")
