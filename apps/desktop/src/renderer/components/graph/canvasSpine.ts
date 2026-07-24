import type { Edge, Node } from "@xyflow/react";
import type { SimpleTurnData } from "./SimpleTurnNode";
import type { TurnGroupData } from "./TurnGroupNode";
import {
  TURN_GROUP_HEADER_H,
  TURN_GROUP_NOTES_FOOTER_H,
  TURN_GROUP_PAD,
} from "./TurnGroupNode";
import type { TurnSummaryData } from "./TurnSummaryNode";
import { namespaceId, parseNamespacedId } from "./ids";
import type { WaveBand } from "./scene";
import {
  GAP_Y,
  SIMPLE_NODE_HEIGHT,
  TEAM_NODE_HEIGHT,
  TURN_NODE_WIDTH,
  type TurnItem,
} from "./useCanvasTurns";
import type { TurnLayoutSlice } from "./useGraphLayout";
import { layoutStructureSig } from "./useLayoutMorph";

const TURN_GROUP_FALLBACK_W = 760;
const TURN_GROUP_FALLBACK_H = 470;

/** One turn's projected DAG (from {@link projectTurnGraph}) + its patch map. */
export interface CanvasTurnProjection {
  layoutNodes: Node[];
  presentData: Map<string, Node["data"]>;
  edges: Edge[];
  lanes: WaveBand[];
  debateStages: WaveBand[];
}

export interface GroupOrigin {
  x: number;
  y: number;
  width: number;
  height: number;
}

function dedupeRoles(exec: NonNullable<TurnItem["exec"]>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const a of exec.agents) {
    const r = a.role?.trim();
    if (!r || seen.has(r)) continue;
    seen.add(r);
    out.push(r);
  }
  return out;
}

/** Nest a turn-DAG node under the turn compound (header + pad). */
function nestUnderTurn(node: Node, turnId: string): Node {
  if (node.parentId) {
    return {
      ...node,
      id: namespaceId(turnId, node.id),
      parentId: namespaceId(turnId, node.parentId),
      extent: "parent",
    };
  }
  return {
    ...node,
    id: namespaceId(turnId, node.id),
    parentId: turnId,
    extent: "parent",
    position: {
      x: node.position.x + TURN_GROUP_PAD,
      y: node.position.y + TURN_GROUP_HEADER_H + TURN_GROUP_PAD,
    },
  };
}

export interface BuildTurnSpineParams {
  turns: TurnItem[];
  expandedTurnSet: ReadonlySet<string>;
  projectedByTurn: Map<string, CanvasTurnProjection>;
  turnLayouts: Record<string, TurnLayoutSlice>;
  effectiveFocus: string | null;
  morphing: boolean;
  keyboardFocusId: string | null;
  /** Marked-seen turn ids (mutated in place — drives the simple-turn enter anim). */
  seenTurns: Set<string>;
  /** True only for the very first spine build (suppresses enter anim). */
  firstSpine: boolean;
  maximizeTurn: (turnId: string) => void;
  onCollapseTurn: (turnId: string) => void;
}

export interface TurnSpine {
  layoutNodes: Node[];
  layoutEdges: Edge[];
  focusedGroupOrigin: GroupOrigin | null;
}

/**
 * Stack every turn into the vertical spine — expanded team turns become compound
 * turnGroups holding their nested DAG; folded team / simple turns become summary
 * nodes. Returns the focused turn's group origin for band offsetting.
 */
export function buildTurnSpine({
  turns,
  expandedTurnSet,
  projectedByTurn,
  turnLayouts,
  effectiveFocus,
  morphing,
  keyboardFocusId,
  seenTurns,
  firstSpine,
  maximizeTurn,
  onCollapseTurn,
}: BuildTurnSpineParams): TurnSpine {
  const outNodes: Node[] = [];
  const outEdges: Edge[] = [];
  let y = 0;
  const lastTurnId = turns[turns.length - 1]?.id;
  let groupOrigin: GroupOrigin | null = null;

  for (const t of turns) {
    const expanded = t.kind === "team" && expandedTurnSet.has(t.id);
    const projected = projectedByTurn.get(t.id);
    const slice = turnLayouts[t.id];

    if (expanded && projected && slice?.layoutReady && slice.bbox) {
      const notes = t.exec?.teamNotes;
      const notesFooter =
        (notes?.length ?? 0) > 0 ? TURN_GROUP_NOTES_FOOTER_H : 0;
      const width = Math.max(
        TURN_GROUP_FALLBACK_W,
        slice.bbox.width + TURN_GROUP_PAD * 2,
      );
      // Height follows placed-content bbox only (host contract). Do not floor
      // to FALLBACK_H after layout — that recreated the “content at top /
      // empty band below” sink sibling of the old ELK dead zone.
      const height =
        TURN_GROUP_HEADER_H +
        slice.bbox.height +
        TURN_GROUP_PAD * 2 +
        notesFooter;
      const groupX = -(width / 2);
      const groupData: TurnGroupData = {
        messageId: t.id,
        taskSummary: t.exec?.taskSummary || t.prompt || "团队回合",
        pendingDecisions: t.pendingDecisions,
        recoverable: t.recoverable,
        onMaximize: () => maximizeTurn(t.id),
        onCollapse: () => onCollapseTurn(t.id),
        teamNotes: notes,
        status: t.exec?.status,
      };
      outNodes.push({
        id: t.id,
        type: "turnGroup",
        position: { x: groupX, y },
        style: { width, height },
        data: groupData,
        draggable: false,
        zIndex: 0,
        className: morphing ? "graph-layout-morphing" : undefined,
      });
      if (t.id === effectiveFocus) {
        groupOrigin = { x: groupX, y, width, height };
      }

      for (const n of projected.layoutNodes) {
        const nested = nestUnderTurn(n, t.id);
        const classes = [
          nested.className,
          morphing ? "graph-layout-morphing" : "",
          keyboardFocusId === nested.id ? "graph-keyboard-focus" : "",
        ]
          .filter(Boolean)
          .join(" ");
        nested.className = classes || undefined;
        outNodes.push(nested);
      }
      y += height + GAP_Y;
    } else if (expanded && t.kind === "team") {
      // Expanded but layout still computing — placeholder compound.
      const notes = t.exec?.teamNotes;
      const notesFooter =
        (notes?.length ?? 0) > 0 ? TURN_GROUP_NOTES_FOOTER_H : 0;
      const width = TURN_GROUP_FALLBACK_W;
      const height = TURN_GROUP_FALLBACK_H + notesFooter;
      const groupX = -(width / 2);
      const groupData: TurnGroupData = {
        messageId: t.id,
        taskSummary: t.exec?.taskSummary || t.prompt || "团队回合",
        pendingDecisions: t.pendingDecisions,
        recoverable: t.recoverable,
        onMaximize: () => maximizeTurn(t.id),
        onCollapse: () => onCollapseTurn(t.id),
        teamNotes: notes,
        status: t.exec?.status,
      };
      outNodes.push({
        id: t.id,
        type: "turnGroup",
        position: { x: groupX, y },
        style: { width, height },
        data: groupData,
        draggable: false,
        zIndex: 0,
      });
      if (t.id === effectiveFocus) {
        groupOrigin = { x: groupX, y, width, height };
      }
      y += height + GAP_Y;
    } else if (t.kind === "team") {
      const exec = t.exec;
      const noteCount = exec?.teamNotes.length ?? 0;
      const data: TurnSummaryData = {
        taskSummary: exec?.taskSummary || t.prompt || "团队回合",
        status: exec?.status ?? "planning",
        roles: exec ? dedupeRoles(exec) : [],
        agentCount: exec?.agents.length ?? 0,
        completed: exec?.progress.completed ?? 0,
        total: exec?.progress.total ?? 0,
        pendingDecisions: t.pendingDecisions,
        recoverable: t.recoverable,
        noteCount,
      };
      outNodes.push({
        id: t.id,
        type: "teamTurn",
        position: { x: -(TURN_NODE_WIDTH / 2), y },
        data,
        draggable: false,
      });
      y += TEAM_NODE_HEIGHT + (noteCount > 0 ? 28 : 0) + GAP_Y;
    } else {
      const data: SimpleTurnData = {
        prompt: t.prompt,
        answer: t.answer,
        running: t.running,
        enter: t.id === lastTurnId && !firstSpine && !seenTurns.has(t.id),
      };
      outNodes.push({
        id: t.id,
        type: "simpleTurn",
        position: { x: -(TURN_NODE_WIDTH / 2), y },
        data,
        draggable: false,
      });
      y += SIMPLE_NODE_HEIGHT + GAP_Y;
    }
  }

  for (const t of turns) seenTurns.add(t.id);

  for (let i = 1; i < turns.length; i++) {
    outEdges.push({
      id: `${turns[i - 1].id}->${turns[i].id}`,
      source: turns[i - 1].id,
      target: turns[i].id,
      type: "smoothstep",
      selectable: false,
      style: { stroke: "var(--border)" },
    });
  }

  return {
    layoutNodes: outNodes,
    layoutEdges: outEdges,
    focusedGroupOrigin: groupOrigin,
  };
}

/** Patch live presentation data onto layout-stable spine nodes. */
export function patchSpineNodes(
  layoutNodes: Node[],
  turns: TurnItem[],
  projectedByTurn: Map<string, CanvasTurnProjection>,
): Node[] {
  const turnById = new Map(turns.map((t) => [t.id, t]));
  return layoutNodes.map((n) => {
    if (n.type === "turnGroup") {
      const t = turnById.get(n.id);
      if (!t) return n;
      const prev = n.data as TurnGroupData;
      const nextNotes = t.exec?.teamNotes;
      const next: TurnGroupData = {
        ...prev,
        taskSummary: t.exec?.taskSummary || t.prompt || "团队回合",
        pendingDecisions: t.pendingDecisions,
        recoverable: t.recoverable,
        teamNotes: nextNotes,
        status: t.exec?.status,
      };
      if (
        prev.taskSummary === next.taskSummary &&
        prev.pendingDecisions === next.pendingDecisions &&
        prev.recoverable === next.recoverable &&
        prev.status === next.status &&
        prev.teamNotes === nextNotes
      ) {
        return n;
      }
      return { ...n, data: next };
    }
    if (n.type === "teamTurn") {
      const t = turnById.get(n.id);
      if (!t) return n;
      const exec = t.exec;
      const next: TurnSummaryData = {
        taskSummary: exec?.taskSummary || t.prompt || "团队回合",
        status: exec?.status ?? "planning",
        roles: exec ? dedupeRoles(exec) : [],
        agentCount: exec?.agents.length ?? 0,
        completed: exec?.progress.completed ?? 0,
        total: exec?.progress.total ?? 0,
        pendingDecisions: t.pendingDecisions,
        recoverable: t.recoverable,
        noteCount: exec?.teamNotes.length ?? 0,
      };
      const prev = n.data as TurnSummaryData;
      if (
        prev.taskSummary === next.taskSummary &&
        prev.status === next.status &&
        prev.completed === next.completed &&
        prev.total === next.total &&
        prev.pendingDecisions === next.pendingDecisions &&
        prev.recoverable === next.recoverable &&
        prev.agentCount === next.agentCount &&
        prev.noteCount === next.noteCount
      ) {
        return n;
      }
      return { ...n, data: next };
    }
    if (n.type === "simpleTurn") {
      const t = turnById.get(n.id);
      if (!t) return n;
      const prev = n.data as SimpleTurnData;
      if (
        prev.prompt === t.prompt &&
        prev.answer === t.answer &&
        prev.running === t.running
      ) {
        return n;
      }
      return {
        ...n,
        data: {
          ...prev,
          prompt: t.prompt,
          answer: t.answer,
          running: t.running,
        } satisfies SimpleTurnData,
      };
    }
    // Nested DAG child — patch from that turn's presentation map.
    const parsed = parseNamespacedId(n.id);
    if (!parsed) return n;
    const present = projectedByTurn.get(parsed.turnId)?.presentData;
    const freshData = present?.get(parsed.bare);
    if (!freshData || freshData === n.data) return n;
    return { ...n, data: freshData };
  });
}

/** Namespace + append every expanded turn's nested DAG edges to the spine edges. */
export function buildSpineEdges(
  layoutEdges: Edge[],
  projectedByTurn: Map<string, CanvasTurnProjection>,
): Edge[] {
  const spineEdges = layoutEdges.filter((e) => e.type === "smoothstep");
  const nested: Edge[] = [];
  for (const [turnId, proj] of projectedByTurn) {
    for (const e of proj.edges) {
      nested.push({
        ...e,
        id: namespaceId(turnId, e.id),
        source: namespaceId(turnId, e.source),
        target: namespaceId(turnId, e.target),
      });
    }
  }
  return [...nested, ...spineEdges];
}

/** Offset a focused turn's turn-local bands into canvas coordinates. */
export function offsetBandsToGroup(
  bands: WaveBand[],
  groupOrigin: GroupOrigin | null,
): WaveBand[] {
  if (!groupOrigin || bands.length === 0) return [];
  const ox = groupOrigin.x + TURN_GROUP_PAD;
  const oy = groupOrigin.y + TURN_GROUP_HEADER_H + TURN_GROUP_PAD;
  return bands.map((b) => ({
    ...b,
    x: b.x + ox,
    y: b.y + oy,
    labelX: b.labelX + ox,
    labelY: b.labelY + oy,
  }));
}

/** Spine memo invalidation key — turn identity + status-bearing summary fields. */
export function spineInvalidationKey(turns: TurnItem[]): string {
  return turns
    .map((t) => {
      const notes = t.exec?.teamNotes?.length ?? 0;
      const status = t.exec?.status ?? "";
      return `${t.id}:${t.kind}:${t.pendingDecisions}:${t.recoverable ? 1 : 0}:${notes}:${status}`;
    })
    .join("|");
}

/** Morph signature across every expanded turn's structural layout. */
export function spineMorphSig(
  expandedTurnInputs: { turnId: string }[],
  turnLayouts: Record<string, TurnLayoutSlice>,
): string {
  return expandedTurnInputs
    .map(({ turnId }) => {
      const s = turnLayouts[turnId];
      if (s?.layoutError) return `${turnId}:error:${s.layoutError}`;
      if (!s?.layoutReady) return `${turnId}:pending`;
      return `${turnId}:${layoutStructureSig(s.positions, s.nodeHeights, s.nodeSizes)}`;
    })
    .join("||");
}
