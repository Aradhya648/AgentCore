/**
 * Pane-level graph actions — replace per-node callback closures on Document shells.
 * Faces look up by id; Document `data` must not carry onActivate / onToggle closures.
 */

import { createContext, useContext } from "react";

export type GraphActionsValue = {
  activateNode: (id: string) => void;
  toggleUnitExpand: (unitId: string) => void;
  focusAct: (actId: string) => void;
  /** Full-screen drill highlight (Live). */
  litRunId: string | null;
  litEndpointMessageId: string | null;
  taskMessageId: string | null;
  finalAnswerId: string | null;
  /** Conversation turn already terminal — drives captain sink chrome. */
  turnTerminal: boolean;
};

const noopActions: GraphActionsValue = {
  activateNode: () => undefined,
  toggleUnitExpand: () => undefined,
  focusAct: () => undefined,
  litRunId: null,
  litEndpointMessageId: null,
  taskMessageId: null,
  finalAnswerId: null,
  turnTerminal: false,
};

export const GraphActionsContext =
  createContext<GraphActionsValue>(noopActions);

export function useGraphActions(): GraphActionsValue {
  return useContext(GraphActionsContext);
}
