import type { components } from "@agentcore/contract-rest-types";

export type SimulationRunSummaryWire =
  components["schemas"]["SimulationRunSummary"];
export type CreateSimulationRunRequestWire =
  components["schemas"]["CreateSimulationRunRequest"];

/** UI-facing run summary (hour derived from tick when not yet streamed). */
export type SimulationRunView = {
  id: string;
  scenario: string;
  tick: number;
  hour: number;
  status: string;
};

/** Clock hour 0–23 from tick index (24 ticks per day). */
export function hourForTick(tick: number): number {
  return Math.max(0, Math.floor(tick)) % 24;
}

export function runFromWire(raw: SimulationRunSummaryWire): SimulationRunView {
  return {
    id: raw.id,
    scenario: raw.scenario,
    tick: raw.current_tick,
    hour: hourForTick(raw.current_tick),
    status: raw.status,
  };
}
