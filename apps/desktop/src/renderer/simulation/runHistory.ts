import type { SimulationRunView } from "@/simulation/runModel";

const STORAGE_KEY = "agentcore:simulation-run-history";
const MAX_RUNS = 12;

export type SavedSimulationRun = SimulationRunView & {
  seed?: number;
  savedAt: string;
};

function readAll(): SavedSimulationRun[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as SavedSimulationRun[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(runs: SavedSimulationRun[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(runs.slice(0, MAX_RUNS)));
  } catch {
    // ignore quota / private mode
  }
}

export function listSavedRuns(): SavedSimulationRun[] {
  return readAll().sort(
    (a, b) => new Date(b.savedAt).getTime() - new Date(a.savedAt).getTime(),
  );
}

export function rememberRun(
  run: SimulationRunView,
  extra?: { seed?: number },
): void {
  const existing = readAll().filter((r) => r.id !== run.id);
  const entry: SavedSimulationRun = {
    ...run,
    seed: extra?.seed,
    savedAt: new Date().toISOString(),
  };
  writeAll([entry, ...existing]);
}
