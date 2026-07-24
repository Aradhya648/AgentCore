import type { AgentState, RunNode } from "@/stores/execution";
import type { GraphEdge } from "@/stores/graph";
import type {
  AuditCausalGraph,
  AuditCausalNode,
} from "@agentcore/contract-rest-types/audit";

export interface InjectEdgeView {
  from: string;
  to: string;
}

export type InjectInEdgeView = InjectEdgeView;

function dedupeInjectEdges(edges: InjectEdgeView[]): InjectEdgeView[] {
  const seen = new Set<string>();
  const out: InjectEdgeView[] = [];
  for (const edge of edges) {
    const key = `${edge.from}\0${edge.to}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(edge);
  }
  return out;
}

function collectInjectEdges(
  graph: AuditCausalGraph | null | undefined,
): InjectEdgeView[] {
  if (!graph?.edges?.length) return [];
  return dedupeInjectEdges(
    graph.edges
      .filter((e) => e.kind === "inject")
      .map((e) => ({ from: e.from, to: e.to })),
  );
}

/** Current-run inject in-edges from a turn-level causal graph. */
export function filterInjectInEdges(
  graph: AuditCausalGraph | null | undefined,
  runId: string,
): InjectInEdgeView[] {
  return collectInjectEdges(graph).filter((e) => e.to === runId);
}

/** Current-run inject out-edges from a turn-level causal graph. */
export function filterInjectOutEdges(
  graph: AuditCausalGraph | null | undefined,
  runId: string,
): InjectEdgeView[] {
  return collectInjectEdges(graph).filter((e) => e.from === runId);
}

export interface InjectGraphOverlay {
  /** Structural dep edge ids that coincide with an audit inject path. */
  highlightEdgeIds: Set<string>;
  /** Inject paths with no matching dep edge on the collaboration graph. */
  gapEdges: GraphEdge[];
  /** Gap edges to render in the current mode. */
  activeGapEdges: GraphEdge[];
  /** Edge ids to keep bright while inject focus dimming is active. */
  focusedEdgeIds: Set<string>;
  /** Run node ids in the active inject neighborhood. */
  relatedNodeIds: Set<string>;
  /** Dim edges outside {@link focusedEdgeIds} (lit run detail focus). */
  dimUnrelatedEdges: boolean;
}

function injectGapEdgeId(from: string, to: string): string {
  return `inject:${from}->${to}`;
}

function depPairKey(source: string, target: string): string {
  return `${source}\0${target}`;
}

/** Merge audit inject paths onto the structural collaboration graph. */
export function buildInjectGraphOverlay(
  causalGraph: AuditCausalGraph | null | undefined,
  structuralEdges: GraphEdge[],
  options: {
    focusRunId?: string | null;
    showAllInject?: boolean;
  },
): InjectGraphOverlay | null {
  const injectEdges = collectInjectEdges(causalGraph);
  if (injectEdges.length === 0) return null;

  const depEdges = structuralEdges.filter((e) => (e.kind ?? "dep") === "dep");
  const depIdByPair = new Map(
    depEdges.map((e) => [depPairKey(e.source, e.target), e.id] as const),
  );

  const highlightEdgeIds = new Set<string>();
  const gapEdges: GraphEdge[] = [];
  for (const inj of injectEdges) {
    const depId = depIdByPair.get(depPairKey(inj.from, inj.to));
    if (depId) highlightEdgeIds.add(depId);
    else {
      gapEdges.push({
        id: injectGapEdgeId(inj.from, inj.to),
        source: inj.from,
        target: inj.to,
        kind: "inject",
      });
    }
  }

  const focusRunId = options.focusRunId ?? null;
  const showAllInject = options.showAllInject === true;
  if (!focusRunId && !showAllInject) return null;

  const focusedEdgeIds = new Set<string>();
  const relatedNodeIds = new Set<string>();

  if (focusRunId) {
    const neighborhood = injectEdges.filter(
      (e) => e.from === focusRunId || e.to === focusRunId,
    );
    if (neighborhood.length === 0) return null;
    for (const inj of neighborhood) {
      relatedNodeIds.add(inj.from);
      relatedNodeIds.add(inj.to);
      const depId = depIdByPair.get(depPairKey(inj.from, inj.to));
      focusedEdgeIds.add(depId ?? injectGapEdgeId(inj.from, inj.to));
    }
    return {
      highlightEdgeIds,
      gapEdges,
      activeGapEdges: gapEdges.filter((e) => focusedEdgeIds.has(e.id)),
      focusedEdgeIds,
      relatedNodeIds,
      dimUnrelatedEdges: true,
    };
  }

  for (const inj of injectEdges) {
    relatedNodeIds.add(inj.from);
    relatedNodeIds.add(inj.to);
    const depId = depIdByPair.get(depPairKey(inj.from, inj.to));
    focusedEdgeIds.add(depId ?? injectGapEdgeId(inj.from, inj.to));
  }
  return {
    highlightEdgeIds,
    gapEdges,
    activeGapEdges: gapEdges,
    focusedEdgeIds,
    relatedNodeIds,
    dimUnrelatedEdges: false,
  };
}

export function resolveRunRole(
  runId: string,
  nodes: AuditCausalNode[] | undefined,
  runs: RunNode[],
  agents: AgentState[],
): string {
  const nodeRole = nodes?.find((n) => n.run_id === runId)?.role;
  if (nodeRole) return nodeRole;
  const run = runs.find((r) => r.id === runId);
  if (run) {
    const role = agents.find((a) => a.id === run.agentId)?.role;
    if (role) return role;
  }
  return runId;
}

export function resolveRunTask(runId: string, runs: RunNode[]): string | null {
  return runs.find((r) => r.id === runId)?.task ?? null;
}

export function injectEdgeLabel(
  edge: InjectInEdgeView,
  graph: AuditCausalGraph | null | undefined,
  runs: RunNode[],
  agents: AgentState[],
): { sourceRole: string; sourceTask: string | null; targetRole: string } {
  const nodes = graph?.nodes;
  return {
    sourceRole: resolveRunRole(edge.from, nodes, runs, agents),
    sourceTask: resolveRunTask(edge.from, runs),
    targetRole: resolveRunRole(edge.to, nodes, runs, agents),
  };
}
