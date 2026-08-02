/**
 * Canvas Document/Live host helpers — per-turn ExecutionScope + GraphActions so
 * nested DAG faces subscribe to the correct turn under namespaced RF ids.
 */

import { ExecutionScopeContext } from "@/stores/execution";
import type { EdgeProps, NodeProps } from "@xyflow/react";
import {
  type ComponentType,
  type ReactNode,
  createContext,
  useContext,
} from "react";
import type { CanvasTurnProjection } from "./canvasSpine";
import { GraphActionsContext, type GraphActionsValue } from "./graphActions";
import {
  GraphCaptainAnswerContext,
  GraphCaptainRunIdContext,
  GraphDocumentModeContext,
  type GraphInjectPaint,
  GraphInjectPaintContext,
  GraphSceneContext,
} from "./graphLive";
import { parseNamespacedId } from "./ids";
import type { GraphScene } from "./scene";

export type CanvasScopeBag = {
  projectedByTurn: Map<string, CanvasTurnProjection>;
  graphActionsForTurn: (turnId: string) => GraphActionsValue;
  fallbackActions: GraphActionsValue;
};

const CanvasScopeBagContext = createContext<CanvasScopeBag | null>(null);

export function CanvasDocumentProviders({
  children,
  scopeBag,
  injectPaint,
  finalAnswer,
}: {
  children: ReactNode;
  scopeBag: CanvasScopeBag;
  injectPaint: GraphInjectPaint;
  finalAnswer: { content: string } | null;
}) {
  return (
    <GraphDocumentModeContext.Provider value={true}>
      <CanvasScopeBagContext.Provider value={scopeBag}>
        <GraphActionsContext.Provider value={scopeBag.fallbackActions}>
          <GraphInjectPaintContext.Provider value={injectPaint}>
            <GraphCaptainAnswerContext.Provider value={finalAnswer}>
              {children}
            </GraphCaptainAnswerContext.Provider>
          </GraphInjectPaintContext.Provider>
        </GraphActionsContext.Provider>
      </CanvasScopeBagContext.Provider>
    </GraphDocumentModeContext.Provider>
  );
}

function TurnLiveScope({
  turnId,
  actions,
  scene,
  captainRunId,
  children,
}: {
  turnId: string | null;
  actions: GraphActionsValue;
  scene: GraphScene | null;
  captainRunId: string | null;
  children: ReactNode;
}) {
  return (
    <ExecutionScopeContext.Provider value={turnId}>
      <GraphActionsContext.Provider value={actions}>
        <GraphSceneContext.Provider value={scene}>
          <GraphCaptainRunIdContext.Provider value={captainRunId}>
            {children}
          </GraphCaptainRunIdContext.Provider>
        </GraphSceneContext.Provider>
      </GraphActionsContext.Provider>
    </ExecutionScopeContext.Provider>
  );
}

function useTurnLiveScope(rfId: string) {
  const bag = useContext(CanvasScopeBagContext);
  const parsed = parseNamespacedId(rfId);
  const turnId = parsed?.turnId ?? null;
  const proj = turnId ? bag?.projectedByTurn.get(turnId) : undefined;
  const actions =
    turnId && bag
      ? bag.graphActionsForTurn(turnId)
      : (bag?.fallbackActions ?? null);
  return {
    turnId,
    actions,
    scene: proj?.scene ?? null,
    captainRunId: proj?.captainRunId ?? null,
  };
}

/** Wrap a DAG node type so Live hooks see that turn's ExecutionScope. */
export function withCanvasTurnScope<P extends NodeProps>(
  Node: ComponentType<P>,
): ComponentType<P> {
  function Scoped(props: P) {
    const scope = useTurnLiveScope(props.id);
    if (!scope.actions) return <Node {...props} />;
    return (
      <TurnLiveScope
        turnId={scope.turnId}
        actions={scope.actions}
        scene={scope.scene}
        captainRunId={scope.captainRunId}
      >
        <Node {...props} />
      </TurnLiveScope>
    );
  }
  Scoped.displayName = `CanvasScope(${Node.displayName ?? Node.name ?? "Node"})`;
  return Scoped;
}

/** Wrap StepEdge so animated / inject Live reads the namespaced turn. */
export function withCanvasEdgeTurnScope(
  Edge: ComponentType<EdgeProps>,
): ComponentType<EdgeProps> {
  function Scoped(props: EdgeProps) {
    const idForScope = props.id || props.source || props.target;
    const scope = useTurnLiveScope(idForScope);
    if (!scope.actions) return <Edge {...props} />;
    return (
      <TurnLiveScope
        turnId={scope.turnId}
        actions={scope.actions}
        scene={scope.scene}
        captainRunId={scope.captainRunId}
      >
        <Edge {...props} />
      </TurnLiveScope>
    );
  }
  Scoped.displayName = `CanvasEdgeScope(${Edge.displayName ?? Edge.name ?? "Edge"})`;
  return Scoped;
}
