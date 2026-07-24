import type { GraphLayout } from "@/stores/graph";
import type { Edge, Node } from "@xyflow/react";
import type { ActCardLayout } from "./actLod";
import {
  type FlowEdgeProjectionInput,
  projectActCardNodes,
  projectFlowEdges,
  projectFlowNodes,
} from "./projectFlowGraph";
import { type WaveBand, projectSceneBands } from "./scene";

export interface ProjectTurnGraphInput extends FlowEdgeProjectionInput {
  /** Placed-content bbox (drives strip band geometry); null before layout. */
  bbox: { width: number; height: number } | null;
  /** Folded-act summary cards (幕级 LOD); [] for single-act turns. */
  actCards: ActCardLayout[];
  /** Layout kind for band orientation (= effective resolved layout). */
  layoutKind: GraphLayout;
  /** Focus a folded act (click on its 幕摘要卡). */
  onFocusAct: (actId: string) => void;
}

export interface ProjectedTurnGraph {
  nodes: Node[];
  edges: Edge[];
  /** WaveLanes layer (act bands ≥2 acts, else wave / delegate bands). */
  lanes: WaveBand[];
  /** DebateStageBands layer (第 N 轮 / 结辩). */
  debateStages: WaveBand[];
}

/** Project one turn's scene + layout into ReactFlow nodes / edges / bands. */
export function projectTurnGraph(
  input: ProjectTurnGraphInput,
): ProjectedTurnGraph {
  const {
    edges: graphEdges,
    injectOverlay,
    bbox,
    actCards,
    layoutKind,
    onFocusAct,
    ...base
  } = input;

  const runNodes = projectFlowNodes(base);
  // 幕级 LOD：非聚焦幕渲染为一张幕摘要卡（点击聚焦）。单幕回合 actCards 恒空。
  const cardNodes =
    actCards.length > 0
      ? projectActCardNodes(
          base.scene,
          actCards,
          base.handleDirection,
          onFocusAct,
        )
      : [];
  const nodes = cardNodes.length > 0 ? [...runNodes, ...cardNodes] : runNodes;

  const edges = projectFlowEdges({ ...base, edges: graphEdges, injectOverlay });

  // Bands come from the scene (structural membership) projected to pixels here.
  const lanes = projectSceneBands(
    base.scene.bands.lanes,
    base.positions,
    bbox,
    layoutKind,
  );
  const debateStages = projectSceneBands(
    base.scene.bands.debateStages,
    base.positions,
    null,
    layoutKind,
  );

  return { nodes, edges, lanes, debateStages };
}
