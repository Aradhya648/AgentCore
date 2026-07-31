"""Admin replay run projection — turn_journal → lightweight ReplayRun list."""

from __future__ import annotations

from agentcore.api.routes.admin._shared import _project_runs, _project_spans


def _multi_agent_journal() -> list[dict]:
    return [
        {
            "kind": "run_plan",
            "payload": {
                "execution_id": "e1",
                "plan_type": "multi_agent",
                "agents": [{"id": "w1", "role": "研究员", "thinking": True}],
                "runs": [
                    {
                        "id": "r1",
                        "agent_id": "w1",
                        "task": "调研方案",
                        "depends_on": [],
                        "parent_run_id": None,
                    },
                ],
            },
            "ts": "t0",
        },
        {
            "kind": "run_started",
            "payload": {
                "run_id": "r1",
                "agent_id": "w1",
                "kind": "agent",
                "parent_run_id": "cap",
            },
            "ts": "t1",
        },
        {
            "kind": "message_final",
            "payload": {
                "run_id": "r1",
                "phase": "completed",
                "content": "调研全文：方案 A 最优",
                "reasoning": "",
            },
            "ts": None,
        },
        {
            "kind": "run_completed",
            "payload": {
                "run_id": "r1",
                "agent_id": "w1",
                "output_summary": "完成调研",
                "role": "member",
                "debrief": {
                    "summary": "完成调研",
                    "key_points": ["横评 A/B/C", "A 成本最低"],
                },
            },
            "ts": "t2",
        },
        {
            "kind": "llm_call",
            "payload": {
                "run_id": "r1",
                "round_idx": 0,
                "finish_reason": "stop",
                "usage": {"input": 10, "output": 20},
            },
            "ts": None,
        },
        {
            "kind": "tool_call",
            "payload": {
                "run_id": "r1",
                "tool_call_id": "tc1",
                "name": "web_search",
                "arguments": '{"q": "x"}',
                "result": "ok",
                "success": True,
            },
            "ts": None,
        },
        {"kind": "turn_end", "payload": {"finish_reason": "end_turn"}, "ts": None},
    ]


def test_project_runs_empty_for_plain_tool_journal():
    """Plain chat journal (llm/tool only, no team surface) → no ReplayRun."""
    entries = [
        {
            "kind": "llm_call",
            "payload": {
                "run_id": "r1",
                "round_idx": 0,
                "finish_reason": "tool_calls",
                "usage": {"input": 1, "output": 2},
            },
            "ts": None,
        },
        {
            "kind": "tool_call",
            "payload": {
                "run_id": "r1",
                "name": "read_file",
                "arguments": "{}",
                "result": "x",
                "success": True,
            },
            "ts": None,
        },
    ]
    assert _project_runs(entries) == []
    assert len(_project_spans(entries)) == 2


def test_project_runs_lifts_message_final_and_tree():
    runs = _project_runs(_multi_agent_journal())
    assert len(runs) == 1
    r = runs[0]
    assert r.run_id == "r1"
    assert r.agent_id == "w1"
    assert r.task == "调研方案"
    assert r.status == "completed"
    assert r.parent_run_id == "cap"
    assert r.depends_on == []
    assert r.content == "调研全文：方案 A 最优"
    assert r.output_summary == "完成调研"
    assert r.role == "member"
    assert r.debrief is not None
    assert r.debrief["summary"] == "完成调研"
    assert r.error is None

    spans = _project_spans(_multi_agent_journal())
    assert [s.kind for s in spans] == ["llm", "tool"]
    assert spans[0].run_id == "r1"
    assert spans[1].name == "web_search"


def test_project_runs_empty_entries():
    assert _project_runs([]) == []
