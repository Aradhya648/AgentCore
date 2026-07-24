"""Unit tests for audit causal graph rebuild."""

from agentcore.runtime.audit.causal import build_causal_graph


def test_causal_graph_parent_depends_inject():
    rows = [
        type(
            "Row",
            (),
            {
                "action": "delegate.plan",
                "run_id": "captain-1",
                "parent_run_id": None,
                "detail": {
                    "tasks": [
                        {"run_id": "w1", "role": "A", "depends_on": []},
                        {"run_id": "w2", "role": "B", "depends_on": ["w1"]},
                    ]
                },
            },
        )(),
        type(
            "Row",
            (),
            {
                "action": "context.inject",
                "run_id": "w2",
                "parent_run_id": None,
                "detail": {"source_run_ids": ["w1"]},
            },
        )(),
    ]
    graph = build_causal_graph(rows)
    edge_kinds = {(e["from"], e["to"], e["kind"]) for e in graph["edges"]}
    assert ("captain-1", "w1", "parent") in edge_kinds
    assert ("captain-1", "w2", "parent") in edge_kinds
    assert ("w1", "w2", "depends_on") in edge_kinds
    assert ("w1", "w2", "inject") in edge_kinds
    assert {n["run_id"] for n in graph["nodes"]} >= {"captain-1", "w1", "w2"}
