import type { SSEEvent } from "@agentcore/contract-types";
import type { ProjectedTurn } from "./projectedTurn";

/** Minimal shape shared by committed turn-fold conformance vectors. */
export interface TurnFixtureWire {
  name: string;
  description?: string;
  events: SSEEvent[];
  projected: ProjectedTurn;
}

/** True for turn-fold vectors; false for auxiliary blobs and simulation fold goldens. */
export function isTurnFixture(raw: unknown): raw is TurnFixtureWire {
  if (typeof raw !== "object" || raw === null) return false;
  const o = raw as Record<string, unknown>;
  if (typeof o.name !== "string" || !Array.isArray(o.events)) return false;
  const projected = o.projected;
  return (
    typeof projected === "object" &&
    projected !== null &&
    "status" in (projected as Record<string, unknown>)
  );
}
