"""Rebuild turn-level causal graph from append-only audit rows (design C)."""

from __future__ import annotations

from typing import Any, Protocol


class _AuditRow(Protocol):
    action: str
    run_id: str | None
    parent_run_id: str | None
    detail: dict[str, Any]


def build_causal_graph(rows: list[_AuditRow]) -> dict[str, Any]:
    """Build ``{nodes, edges}`` from audit events for one turn.

    Edge kinds:
    - ``parent``: nested delegation (``parent_run_id`` / ``run.started``)
    - ``depends_on``: plan dependency (``delegate.plan`` detail ``tasks[].depends_on``)
    - ``inject``: context injection (``context.inject`` ``source_run_ids``)
    """
    node_meta: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def _ensure_node(run_id: str, *, role: str | None = None, parent: str | None = None) -> None:
        if not run_id:
            return
        meta = node_meta.setdefault(run_id, {"run_id": run_id})
        if role is not None:
            meta["role"] = role
        if parent is not None:
            meta.setdefault("parent_run_id", parent)

    def _add_edge(kind: str, source: str, target: str) -> None:
        if not source or not target or source == target:
            return
        key = (kind, source, target)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"kind": kind, "from": source, "to": target})
        _ensure_node(source)
        _ensure_node(target)

    for row in rows:
        if row.action == "delegate.plan":
            tasks = row.detail.get("tasks") if isinstance(row.detail, dict) else None
            if not isinstance(tasks, list):
                continue
            captain = row.run_id or row.parent_run_id
            if captain:
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    run_id = str(task.get("run_id") or "")
                    if run_id:
                        _ensure_node(run_id, role=task.get("role"), parent=captain)
                        _add_edge("parent", captain, run_id)
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                run_id = str(task.get("run_id") or "")
                if not run_id:
                    continue
                depends = task.get("depends_on")
                if not isinstance(depends, list):
                    continue
                for dep in depends:
                    _add_edge("depends_on", str(dep), run_id)

        elif row.action == "run.started":
            run_id = row.run_id
            parent = row.parent_run_id or (
                row.detail.get("parent_run_id") if isinstance(row.detail, dict) else None
            )
            if run_id:
                _ensure_node(run_id, parent=str(parent) if parent else None)
                if parent:
                    _add_edge("parent", str(parent), run_id)

        elif row.action == "context.inject":
            target = row.run_id
            if not target or not isinstance(row.detail, dict):
                continue
            sources = row.detail.get("source_run_ids")
            if not isinstance(sources, list):
                continue
            for source in sources:
                _add_edge("inject", str(source), target)

    nodes = sorted(node_meta.values(), key=lambda n: n["run_id"])
    return {"nodes": nodes, "edges": edges}
