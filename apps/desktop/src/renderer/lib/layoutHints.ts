/**
 * Layout hints — the single source for「接续链归哪个子队盒」(which compound box a
 * continuation chain belongs to) and edge/compound ownership.
 *
 * This is the derivation that used to be duplicated three ways (elk-layout's
 * `revisionRootOf`/`containsTeam`/`innermostTeamForEdge`, projectFlowGraph's
 * `layoutOwnerOf`/`innermostGroupForRun`, and helpers' `unitOf`). It now lives
 * here once; {@link computeLayout} consumes it to build ELK compounds and
 * {@link buildGraphScene} exposes {@link LayoutHints.nodeGroup} so the ReactFlow
 * projection reads the same conclusion instead of re-deriving it.
 *
 * Continuation chains are read from `continuation` edges (the scene's linearised
 * 原始→续×1→续×2 output), never re-walked from run fields, so the compound child
 * sets stay byte-identical to what the graph structure already declared.
 *
 * NOTE: the edge-ownership and node-ownership reduces are deliberately NOT the
 * same tie-break — edges are emitted at the OUTERMOST compound containing both
 * endpoints (matches ELK's historical `innermostTeamForEdge`), while a node is
 * placed in the INNERMOST compound containing it (matches the projection's
 * historical `innermostGroupForRun`). This asymmetry is preserved verbatim; a
 * pure R1 refactor must not "fix" it.
 */
import type { GraphEdge } from "@/stores/graph";

/** Sub-team compound shape (mirrors helpers' `SubTeam` / elk's `SubTeamInput`). */
export interface LayoutHintTeam {
  parentId: string;
  memberIds: string[];
  groupId: string;
}

export interface LayoutHints {
  /** Base run id → its continuation descendants that co-locate in the base's
   * compound (transitive over `continuation` edges). Empty for a leaf. */
  continuationDescendants: Map<string, string[]>;
  /** Edge id → groupId of the compound that OWNS the edge (outermost containing
   * both endpoints); `null` = the ELK root (cross-team / top-level edge). */
  edgeGroup: Map<string, string | null>;
  /** Run ids that render inside some compound (excluded from ELK top-level). */
  inTeam: Set<string>;
  /** Run id → groupId of the INNERMOST compound it renders inside; `null` =
   * top-level. The single「接续链归盒」conclusion the projection consumes. */
  nodeGroup: Map<string, string | null>;
}

export function computeLayoutHints(
  subTeams: readonly LayoutHintTeam[],
  edges: readonly GraphEdge[],
): LayoutHints {
  const subTeamByParent = new Map(subTeams.map((st) => [st.parentId, st]));

  // Continuation chains (原始 → 续×1 → 续×2…) read from continuation edges.
  const revisionSuccessors = new Map<string, string[]>();
  const revisionSourceOf = new Map<string, string>();
  for (const e of edges) {
    if (e.kind !== "continuation") continue;
    const arr = revisionSuccessors.get(e.source);
    if (arr) arr.push(e.target);
    else revisionSuccessors.set(e.source, [e.target]);
    revisionSourceOf.set(e.target, e.source);
  }
  const revisionRootOf = (id: string): string => {
    let cur = id;
    const seen = new Set<string>();
    while (revisionSourceOf.has(cur) && !seen.has(cur)) {
      seen.add(cur);
      cur = revisionSourceOf.get(cur) as string;
    }
    return cur;
  };
  const revisionDescendantsOf = (id: string): string[] => {
    const out: string[] = [];
    const seen = new Set<string>([id]);
    const stack = [id];
    while (stack.length > 0) {
      const n = stack.pop() as string;
      for (const t of revisionSuccessors.get(n) ?? []) {
        if (seen.has(t)) continue;
        seen.add(t);
        out.push(t);
        stack.push(t);
      }
    }
    return out;
  };

  const structurallyContainsTeam = (
    st: LayoutHintTeam,
    id: string,
  ): boolean => {
    if (id === st.parentId) return true;
    for (const m of st.memberIds) {
      if (id === m) return true;
      const nested = subTeamByParent.get(m);
      if (nested && structurallyContainsTeam(nested, id)) return true;
    }
    return false;
  };
  // A revision belongs to whichever team owns its revision root.
  const containsTeam = (st: LayoutHintTeam, id: string): boolean =>
    structurallyContainsTeam(st, id) ||
    structurallyContainsTeam(st, revisionRootOf(id));

  // Edge ownership: OUTERMOST team containing both endpoints (see file note).
  const innermostTeamForEdge = (
    source: string,
    target: string,
  ): LayoutHintTeam | null => {
    const candidates = subTeams.filter(
      (st) => containsTeam(st, source) && containsTeam(st, target),
    );
    if (candidates.length === 0) return null;
    return candidates.reduce((best, st) => {
      if (best === st) return best;
      const stNestedInBest = best.memberIds.includes(st.parentId);
      const bestNestedInSt = st.memberIds.includes(best.parentId);
      if (stNestedInBest) return best;
      if (bestNestedInSt) return st;
      return best;
    });
  };

  // Node ownership: INNERMOST team containing the node (see file note).
  const innermostTeamForNode = (id: string): LayoutHintTeam | null => {
    const candidates = subTeams.filter((st) => containsTeam(st, id));
    if (candidates.length === 0) return null;
    return candidates.reduce((best, st) => {
      if (best === st) return best;
      if (best.memberIds.includes(st.parentId)) return st;
      if (st.memberIds.includes(best.parentId)) return best;
      return best;
    });
  };

  const continuationDescendants = new Map<string, string[]>();
  const inTeam = new Set<string>();
  for (const st of subTeams) {
    for (const base of [st.parentId, ...st.memberIds]) {
      const desc = revisionDescendantsOf(base);
      continuationDescendants.set(base, desc);
      inTeam.add(base);
      for (const d of desc) inTeam.add(d);
    }
  }

  const edgeGroup = new Map<string, string | null>();
  for (const e of edges) {
    edgeGroup.set(
      e.id,
      innermostTeamForEdge(e.source, e.target)?.groupId ?? null,
    );
  }

  const nodeGroup = new Map<string, string | null>();
  for (const id of inTeam) {
    nodeGroup.set(id, innermostTeamForNode(id)?.groupId ?? null);
  }

  return { continuationDescendants, edgeGroup, inTeam, nodeGroup };
}
