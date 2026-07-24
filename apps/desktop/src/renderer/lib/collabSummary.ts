import type { TurnCollabMetrics } from "@/types/events";

const ORCHESTRATION_PARTS: Array<{
  key: "boundary_yields" | "scope_signals" | "revises" | "escalations";
  label: string;
}> = [
  { key: "boundary_yields", label: "纠偏" },
  { key: "scope_signals", label: "漂移" },
  { key: "revises", label: "唤回" },
  { key: "escalations", label: "上报" },
];

/** Compact non-diagnostic footer line for turn-level orchestration signals. */
export function formatCollabSummary(
  collab: TurnCollabMetrics | undefined,
): string | null {
  if (!collab) return null;
  const segments = ORCHESTRATION_PARTS.filter(
    ({ key }) => (collab[key] ?? 0) > 0,
  ).map(({ key, label }) => `${label} ${collab[key]} 次`);
  return segments.length > 0 ? segments.join(" · ") : null;
}
