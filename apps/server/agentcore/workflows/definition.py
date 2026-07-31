"""Validate + expand user-workflow definitions into delegate-shaped tasks.

First-period kinds: ``agent_step`` | ``human_gate``.
``human_gate`` does not become a worker — it marks every direct predecessor
``checkpoint_after=true`` (wave-boundary user review).
"""

from __future__ import annotations

from typing import Any

from agentcore.runtime.runs.constants import MAX_DELEGATION_TASKS

_ALLOWED_KINDS = frozenset({"agent_step", "human_gate"})


class WorkflowDefinitionError(ValueError):
    """Invalid workflow definition (cycle / empty step / bad edge / over limit)."""


def validate_workflow_definition(definition: dict[str, Any] | None) -> list[str]:
    """Structural checks for save/create drafts (empty canvas is allowed).

    Runnable definitions are enforced by :func:`expand_workflow_to_tasks`
    (must yield ≥1 agent_step). Does not mutate.
    """
    errors: list[str] = []
    if not isinstance(definition, dict):
        return ["definition 必须是对象"]

    nodes = definition.get("nodes")
    edges = definition.get("edges")
    if not isinstance(nodes, list):
        errors.append("nodes 必须是数组")
        nodes = []
    if edges is None:
        edges = []
    elif not isinstance(edges, list):
        errors.append("edges 必须是数组")
        edges = []

    ids: set[str] = set()
    agent_count = 0
    for i, raw in enumerate(nodes):
        if not isinstance(raw, dict):
            errors.append(f"nodes[{i}] 必须是对象")
            continue
        nid = str(raw.get("id") or "").strip()
        if not nid:
            errors.append(f"nodes[{i}] 缺少 id")
            continue
        if nid in ids:
            errors.append(f"节点 id 重复：`{nid}`")
            continue
        ids.add(nid)
        kind = str(raw.get("kind") or "").strip()
        if kind not in _ALLOWED_KINDS:
            errors.append(f"nodes[{i}] kind 须为 agent_step 或 human_gate")
            continue
        if kind == "agent_step":
            agent_count += 1
            role = raw.get("role")
            task = raw.get("task")
            if not isinstance(role, str) or not role.strip():
                errors.append(f"agent_step `{nid}` 须有非空 role")
            if not isinstance(task, str) or not task.strip():
                errors.append(f"agent_step `{nid}` 须有非空 task")
            deliverable = raw.get("deliverable")
            if deliverable is not None and not isinstance(deliverable, dict):
                errors.append(f"agent_step `{nid}` deliverable 须为对象")
        elif kind == "human_gate":
            label = raw.get("label")
            if label is not None and not isinstance(label, str):
                errors.append(f"human_gate `{nid}` label 须为字符串")

    if agent_count > MAX_DELEGATION_TASKS:
        errors.append(f"agent_step 数量不能超过 {MAX_DELEGATION_TASKS}")

    adj: dict[str, list[str]] = {nid: [] for nid in ids}
    for i, raw in enumerate(edges):
        if not isinstance(raw, dict):
            errors.append(f"edges[{i}] 必须是对象")
            continue
        src = str(raw.get("from") or "").strip()
        dst = str(raw.get("to") or "").strip()
        if not src or not dst:
            errors.append(f"edges[{i}] 须有 from / to")
            continue
        if src not in ids:
            errors.append(f"edges[{i}] from `{src}` 不存在")
            continue
        if dst not in ids:
            errors.append(f"edges[{i}] to `{dst}` 不存在")
            continue
        adj[src].append(dst)

    if ids and not errors:
        cycle = _find_cycle(adj)
        if cycle is not None:
            errors.append(f"定义存在环：{' → '.join(cycle)}")

    return errors


def expand_workflow_to_tasks(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand a validated definition into hand-written-delegate-shaped tasks.

    Raises :class:`WorkflowDefinitionError` when invalid.
    """
    errors = validate_workflow_definition(definition)
    if errors:
        raise WorkflowDefinitionError("；".join(errors))

    nodes = list(definition.get("nodes") or [])
    edges = list(definition.get("edges") or [])
    by_id = {str(n["id"]).strip(): n for n in nodes if isinstance(n, dict)}

    # Direct predecessors of each human_gate → those agent_steps get checkpoint_after.
    gate_preds: set[str] = set()
    agent_deps: dict[str, list[str]] = {
        nid: [] for nid, n in by_id.items() if str(n.get("kind") or "") == "agent_step"
    }
    for raw in edges:
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("from") or "").strip()
        dst = str(raw.get("to") or "").strip()
        src_node = by_id.get(src)
        dst_node = by_id.get(dst)
        if src_node is None or dst_node is None:
            continue
        src_kind = str(src_node.get("kind") or "")
        dst_kind = str(dst_node.get("kind") or "")
        if dst_kind == "human_gate" and src_kind == "agent_step":
            gate_preds.add(src)
        if src_kind == "agent_step" and dst_kind == "agent_step":
            agent_deps[dst].append(src)
        # Edges into agent_step from human_gate: treat as through-deps from gate's preds.
        if src_kind == "human_gate" and dst_kind == "agent_step":
            for pred in _direct_preds(src, edges, by_id):
                if str(by_id[pred].get("kind") or "") == "agent_step":
                    agent_deps[dst].append(pred)

    # Preserve declaration order of agent_steps.
    tasks: list[dict[str, Any]] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        if str(n.get("kind") or "") != "agent_step":
            continue
        nid = str(n["id"]).strip()
        deps = list(dict.fromkeys(agent_deps.get(nid) or []))
        item: dict[str, Any] = {
            "id": nid,
            "role": str(n.get("role") or "").strip(),
            "task": str(n.get("task") or "").strip(),
        }
        if deps:
            item["depends_on"] = deps
        if nid in gate_preds:
            item["checkpoint_after"] = True
        deliverable = n.get("deliverable")
        if isinstance(deliverable, dict) and deliverable:
            item["deliverable"] = deliverable
        tasks.append(item)
    if not tasks:
        raise WorkflowDefinitionError("至少需要一个 agent_step")
    return tasks


# Task keys that survive the definition canvas (everything else is phase-1 dropped).
_DEFINITION_TASK_KEYS = frozenset(
    {"id", "role", "task", "depends_on", "checkpoint_after", "deliverable"}
)


def tasks_to_workflow_definition(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Inverse of :func:`expand_workflow_to_tasks` (structure only).

    Each task → ``agent_step``; ``depends_on`` → edges; ``checkpoint_after`` → insert a
    ``human_gate`` after that step (successors connect from the gate). Extra task fields
    (``tools`` / ``max_rounds`` / ``timeout_ms`` / …) are intentionally dropped.
    """
    if not isinstance(tasks, list) or not tasks:
        raise WorkflowDefinitionError("至少需要一个 task")

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    gate_after: dict[str, str] = {}
    seen_ids: set[str] = set()

    for i, raw in enumerate(tasks):
        if not isinstance(raw, dict):
            raise WorkflowDefinitionError(f"tasks[{i}] 必须是对象")
        tid = str(raw.get("id") or "").strip()
        if not tid:
            raise WorkflowDefinitionError(f"tasks[{i}] 缺少 id")
        if tid in seen_ids:
            raise WorkflowDefinitionError(f"task id 重复：`{tid}`")
        seen_ids.add(tid)
        role = raw.get("role")
        task_text = raw.get("task")
        if not isinstance(role, str) or not role.strip():
            raise WorkflowDefinitionError(f"task `{tid}` 须有非空 role")
        if not isinstance(task_text, str) or not task_text.strip():
            raise WorkflowDefinitionError(f"task `{tid}` 须有非空 task")
        node: dict[str, Any] = {
            "id": tid,
            "kind": "agent_step",
            "role": role.strip(),
            "task": task_text.strip(),
        }
        deliverable = raw.get("deliverable")
        if isinstance(deliverable, dict) and deliverable:
            node["deliverable"] = dict(deliverable)
        nodes.append(node)
        if raw.get("checkpoint_after") is True:
            gid = f"gate_after_{tid}"
            if gid in seen_ids:
                raise WorkflowDefinitionError(f"无法插入 human_gate：id `{gid}` 已占用")
            seen_ids.add(gid)
            nodes.append({"id": gid, "kind": "human_gate", "label": "审阅后继续"})
            edges.append({"from": tid, "to": gid})
            gate_after[tid] = gid

    for raw in tasks:
        if not isinstance(raw, dict):
            continue
        tid = str(raw.get("id") or "").strip()
        deps_raw = raw.get("depends_on")
        if deps_raw is None:
            continue
        if not isinstance(deps_raw, list):
            raise WorkflowDefinitionError(f"task `{tid}` depends_on 须为数组")
        for dep in deps_raw:
            src_id = str(dep or "").strip()
            if not src_id:
                continue
            if src_id not in gate_after and src_id not in {
                str(t.get("id") or "").strip() for t in tasks if isinstance(t, dict)
            }:
                raise WorkflowDefinitionError(f"task `{tid}` depends_on `{src_id}` 不存在")
            src = gate_after.get(src_id, src_id)
            edges.append({"from": src, "to": tid})

    definition = {"nodes": nodes, "edges": edges}
    errors = validate_workflow_definition(definition)
    if errors:
        raise WorkflowDefinitionError("；".join(errors))
    return definition


def tasks_dropped_meta_keys(tasks: list[dict[str, Any]]) -> list[str]:
    """Sorted unique task keys not represented on the canvas (for summary notes)."""
    found: set[str] = set()
    for raw in tasks:
        if not isinstance(raw, dict):
            continue
        for key in raw:
            if key not in _DEFINITION_TASK_KEYS:
                found.add(str(key))
    return sorted(found)


def _direct_preds(
    node_id: str,
    edges: list,
    by_id: dict[str, dict[str, Any]],
) -> list[str]:
    out: list[str] = []
    for raw in edges:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("to") or "").strip() != node_id:
            continue
        src = str(raw.get("from") or "").strip()
        if src in by_id:
            out.append(src)
    return out


def _find_cycle(adj: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle path (node ids) or None. Kahn leftover → DFS recover."""
    indeg = {n: 0 for n in adj}
    for _src, dsts in adj.items():
        for d in dsts:
            indeg[d] = indeg.get(d, 0) + 1
    queue = [n for n, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        n = queue.pop()
        seen += 1
        for d in adj.get(n, []):
            indeg[d] -= 1
            if indeg[d] == 0:
                queue.append(d)
    if seen == len(adj):
        return None
    # Recover a concrete cycle for the error message.
    remaining = {n for n, d in indeg.items() if d > 0}
    start = next(iter(remaining))
    path: list[str] = []
    visiting: set[str] = set()

    def dfs(u: str) -> list[str] | None:
        path.append(u)
        visiting.add(u)
        for v in adj.get(u, []):
            if v not in remaining:
                continue
            if v in visiting:
                i = path.index(v)
                return path[i:] + [v]
            found = dfs(v)
            if found is not None:
                return found
        path.pop()
        visiting.discard(u)
        return None

    return dfs(start)
