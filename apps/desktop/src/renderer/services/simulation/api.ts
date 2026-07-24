import { api } from "@/services/api";
import {
  type CreateSimulationRunRequestWire,
  type SimulationRunView,
  runFromWire,
} from "@/simulation/runModel";
import type { components } from "@agentcore/contract-rest-types";

export async function createSimulationRun(
  body: Partial<CreateSimulationRunRequestWire> = {},
): Promise<SimulationRunView> {
  const raw = await api.post<components["schemas"]["SimulationRunSummary"]>(
    "/v1/simulation/runs",
    {
      scenario: body.scenario ?? "town",
      seed: body.seed,
      // Align with Unity client: Desktop launcher defaults to scripted (no real LLM).
      scripted: body.scripted ?? true,
    },
  );
  return runFromWire(raw);
}
