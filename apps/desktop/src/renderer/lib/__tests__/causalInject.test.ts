import {
  buildInjectGraphOverlay,
  filterInjectInEdges,
  injectEdgeLabel,
  resolveRunRole,
} from "@/lib/causalInject";
import type { AgentState, RunNode } from "@/stores/execution";
import type { GraphEdge } from "@/stores/graph";
import type { AuditCausalGraph } from "@agentcore/contract-rest-types/audit";
import { describe, expect, it } from "vitest";

const runs = [
  {
    id: "r1",
    agentId: "w1",
    task: "调研竞品定价",
    status: "completed",
    dependsOn: [],
    parentRunId: null,
    continuesRunId: null,
    receivedContext: [],
    escalations: [],
    durationMs: 1000,
  },
  {
    id: "r2",
    agentId: "w2",
    task: "撰写定价建议",
    status: "completed",
    dependsOn: ["r1"],
    parentRunId: null,
    continuesRunId: null,
    receivedContext: [],
    escalations: [],
    durationMs: 1000,
  },
] as unknown as RunNode[];

const agent = (id: string, role: string): AgentState => ({
  id,
  role,
  thinking: true,
  status: "idle",
  currentRunId: null,
  outputChunks: [],
  reasoningChunks: [],
  toolCalls: [],
  toolProgress: null,
  toolExecutionLive: null,
});

const agents: AgentState[] = [agent("w1", "研究员"), agent("w2", "撰写员")];

const graph: AuditCausalGraph = {
  nodes: [
    { run_id: "r1", role: "研究员" },
    { run_id: "r2", role: "撰写员" },
  ],
  edges: [
    { kind: "depends_on", from: "r1", to: "r2" },
    { kind: "inject", from: "r1", to: "r2" },
    { kind: "inject", from: "r1", to: "r2" },
    { kind: "parent", from: "ceo", to: "r1" },
  ],
};

describe("filterInjectInEdges", () => {
  it("keeps inject in-edges for the selected run", () => {
    expect(filterInjectInEdges(graph, "r2")).toEqual([
      { from: "r1", to: "r2" },
    ]);
  });

  it("drops out-edges and non-inject kinds", () => {
    expect(filterInjectInEdges(graph, "r1")).toEqual([]);
  });

  it("returns empty for null graph", () => {
    expect(filterInjectInEdges(null, "r2")).toEqual([]);
  });
});

describe("resolveRunRole", () => {
  it("prefers causal node role", () => {
    expect(resolveRunRole("r1", graph.nodes, runs, agents)).toBe("研究员");
  });

  it("falls back to execution projection", () => {
    expect(resolveRunRole("r2", [], runs, agents)).toBe("撰写员");
  });

  it("falls back to run id", () => {
    expect(resolveRunRole("missing", [], runs, agents)).toBe("missing");
  });
});

describe("injectEdgeLabel", () => {
  it("labels source and target roles", () => {
    expect(
      injectEdgeLabel({ from: "r1", to: "r2" }, graph, runs, agents),
    ).toEqual({
      sourceRole: "研究员",
      sourceTask: "调研竞品定价",
      targetRole: "撰写员",
    });
  });
});

const depEdges: GraphEdge[] = [
  { id: "r1->r2", source: "r1", target: "r2", kind: "dep" },
];

describe("buildInjectGraphOverlay", () => {
  it("returns null when inactive", () => {
    expect(buildInjectGraphOverlay(graph, depEdges, {})).toBeNull();
  });

  it("highlights coincident dep edge on focus", () => {
    const overlay = buildInjectGraphOverlay(graph, depEdges, {
      focusRunId: "r2",
    });
    expect(overlay).not.toBeNull();
    expect(overlay?.highlightEdgeIds.has("r1->r2")).toBe(true);
    expect(overlay?.focusedEdgeIds.has("r1->r2")).toBe(true);
    expect(overlay?.activeGapEdges).toEqual([]);
    expect(overlay?.dimUnrelatedEdges).toBe(true);
  });

  it("adds gap edge when inject has no dep", () => {
    const gapGraph: AuditCausalGraph = {
      nodes: graph.nodes,
      edges: [{ kind: "inject", from: "r1", to: "r3" }],
    };
    const overlay = buildInjectGraphOverlay(gapGraph, depEdges, {
      focusRunId: "r3",
    });
    expect(overlay?.activeGapEdges).toEqual([
      { id: "inject:r1->r3", source: "r1", target: "r3", kind: "inject" },
    ]);
    expect(overlay?.focusedEdgeIds.has("inject:r1->r3")).toBe(true);
  });

  it("shows all inject paths when toggle on", () => {
    const overlay = buildInjectGraphOverlay(graph, depEdges, {
      showAllInject: true,
    });
    expect(overlay?.dimUnrelatedEdges).toBe(false);
    expect(overlay?.focusedEdgeIds.has("r1->r2")).toBe(true);
  });
});
