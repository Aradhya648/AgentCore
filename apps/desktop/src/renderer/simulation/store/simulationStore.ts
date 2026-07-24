import { create } from "zustand";
import type { SimulationRunView } from "../runModel";

/**
 * Launcher session only — create / remember / exit a sim run before opening AgentTown.
 * Real-time observation lives in apps/town; ST-02 fold is headless in foldSimulation.ts.
 */
export const useSimulationUiStore = create<{
  run: SimulationRunView | null;
  setRun: (run: SimulationRunView | null) => void;
  resetSession: () => void;
}>()((set) => ({
  run: null,
  setRun: (run) => set({ run }),
  resetSession: () => set({ run: null }),
}));
