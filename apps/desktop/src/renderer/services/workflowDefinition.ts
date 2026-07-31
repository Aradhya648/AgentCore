/**
 * User workflow definition (定案 §10.2) — canvas JSON shape + first-wave validation.
 * Kept separate from the REST client so unit tests need no API mocks.
 */

/** Max expandable agent steps — align with global delegate cap (20). */
export const WORKFLOW_MAX_AGENT_STEPS = 20;

export type WorkflowNodeKind = "agent_step" | "human_gate";

export interface WorkflowAgentStepNode {
  id: string;
  kind: "agent_step";
  role: string;
  task: string;
  deliverable?: { form?: string };
}

export interface WorkflowHumanGateNode {
  id: string;
  kind: "human_gate";
  label: string;
}

export type WorkflowDefNode = WorkflowAgentStepNode | WorkflowHumanGateNode;

export interface WorkflowDefEdge {
  from: string;
  to: string;
}

export interface WorkflowDefinition {
  nodes: WorkflowDefNode[];
  edges: WorkflowDefEdge[];
}

export interface WorkflowDefinitionIssue {
  code:
    | "empty_role"
    | "empty_task"
    | "empty_gate_label"
    | "unknown_edge_endpoint"
    | "cycle"
    | "too_many_steps"
    | "duplicate_id"
    | "invalid_kind";
  message: string;
  nodeId?: string;
}

export function emptyWorkflowDefinition(): WorkflowDefinition {
  return { nodes: [], edges: [] };
}

export function newNodeId(prefix = "n"): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

export function createAgentStepNode(
  partial?: Partial<Omit<WorkflowAgentStepNode, "kind">>,
): WorkflowAgentStepNode {
  return {
    id: partial?.id ?? newNodeId("step"),
    kind: "agent_step",
    role: partial?.role ?? "",
    task: partial?.task ?? "",
    deliverable: partial?.deliverable,
  };
}

export function createHumanGateNode(
  partial?: Partial<Omit<WorkflowHumanGateNode, "kind">>,
): WorkflowHumanGateNode {
  return {
    id: partial?.id ?? newNodeId("gate"),
    kind: "human_gate",
    label: partial?.label ?? "等人确认",
  };
}

function hasCycle(ids: string[], edges: WorkflowDefEdge[]): boolean {
  const outs = new Map<string, string[]>();
  for (const id of ids) outs.set(id, []);
  for (const e of edges) {
    outs.get(e.from)?.push(e.to);
  }
  const visiting = new Set<string>();
  const done = new Set<string>();
  const dfs = (id: string): boolean => {
    if (done.has(id)) return false;
    if (visiting.has(id)) return true;
    visiting.add(id);
    for (const next of outs.get(id) ?? []) {
      if (dfs(next)) return true;
    }
    visiting.delete(id);
    done.add(id);
    return false;
  };
  return ids.some((id) => dfs(id));
}

/** Structural validation for save / run. */
export function validateWorkflowDefinition(
  def: WorkflowDefinition,
): WorkflowDefinitionIssue[] {
  const issues: WorkflowDefinitionIssue[] = [];
  const seen = new Set<string>();
  let agentCount = 0;

  for (const node of def.nodes) {
    if (seen.has(node.id)) {
      issues.push({
        code: "duplicate_id",
        message: `重复节点 id：${node.id}`,
        nodeId: node.id,
      });
      continue;
    }
    seen.add(node.id);

    if (node.kind === "agent_step") {
      agentCount += 1;
      if (!node.role.trim()) {
        issues.push({
          code: "empty_role",
          message: "队员步骤须填写角色",
          nodeId: node.id,
        });
      }
      if (!node.task.trim()) {
        issues.push({
          code: "empty_task",
          message: "队员步骤须填写任务说明",
          nodeId: node.id,
        });
      }
    } else if (node.kind === "human_gate") {
      if (!node.label.trim()) {
        issues.push({
          code: "empty_gate_label",
          message: "等人关卡须填写标签",
          nodeId: node.id,
        });
      }
    } else {
      issues.push({
        code: "invalid_kind",
        message: "未知节点类型",
        nodeId: (node as WorkflowDefNode).id,
      });
    }
  }

  if (agentCount > WORKFLOW_MAX_AGENT_STEPS) {
    issues.push({
      code: "too_many_steps",
      message: `队员步骤不得超过 ${WORKFLOW_MAX_AGENT_STEPS} 个`,
    });
  }

  for (const e of def.edges) {
    if (!seen.has(e.from) || !seen.has(e.to)) {
      issues.push({
        code: "unknown_edge_endpoint",
        message: `连线端点不存在：${e.from} → ${e.to}`,
      });
    }
  }

  if (hasCycle([...seen], def.edges)) {
    issues.push({ code: "cycle", message: "工作流图不能有环" });
  }

  return issues;
}

/** Normalize unknown JSON into a definition (drops invalid entries). */
export function parseWorkflowDefinition(raw: unknown): WorkflowDefinition {
  if (!raw || typeof raw !== "object") return emptyWorkflowDefinition();
  const obj = raw as { nodes?: unknown; edges?: unknown };
  const nodes: WorkflowDefNode[] = [];
  if (Array.isArray(obj.nodes)) {
    for (const n of obj.nodes) {
      if (!n || typeof n !== "object") continue;
      const row = n as Record<string, unknown>;
      const id = typeof row.id === "string" ? row.id : "";
      if (!id) continue;
      if (row.kind === "agent_step") {
        const deliverable =
          row.deliverable && typeof row.deliverable === "object"
            ? {
                form:
                  typeof (row.deliverable as { form?: unknown }).form ===
                  "string"
                    ? (row.deliverable as { form: string }).form
                    : undefined,
              }
            : undefined;
        nodes.push({
          id,
          kind: "agent_step",
          role: typeof row.role === "string" ? row.role : "",
          task: typeof row.task === "string" ? row.task : "",
          deliverable,
        });
      } else if (row.kind === "human_gate") {
        nodes.push({
          id,
          kind: "human_gate",
          label: typeof row.label === "string" ? row.label : "",
        });
      }
    }
  }
  const edges: WorkflowDefEdge[] = [];
  if (Array.isArray(obj.edges)) {
    for (const e of obj.edges) {
      if (!e || typeof e !== "object") continue;
      const row = e as Record<string, unknown>;
      if (typeof row.from === "string" && typeof row.to === "string") {
        edges.push({ from: row.from, to: row.to });
      }
    }
  }
  return { nodes, edges };
}
