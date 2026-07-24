// Per-turn cost lookup for the mobile client (成本呈现; 团队工资单 read side).
//
// A finished turn's spend is replayed from the cost_events ledger by message_id
// (api/routes 工资单). The LIVE turn already carries its cost in the SSE message_end
// (the fold's ProjectedTurn.cost), so this endpoint is only for RELOADED history — a
// persisted MessageDetail does not carry cost. Supplementary: callers swallow failures
// (cost must never break the chat). REST DTOs track OpenAPI via contract-rest-types.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

type TurnCost = Schemas["TurnCost"];

/**
 * A turn's persisted display money in integer nano-USD. Prefers ledger `cost.total`;
 * falls back to `estimated_cost.total` for BYOK. Returns null when neither is >0.
 */
export async function getMessageCostDisplay(
  messageId: string,
): Promise<{ nano: number; estimated: boolean; unpriced?: boolean } | null> {
  try {
    const res = await apiFetch(`/v1/messages/${messageId}/cost`);
    if (!res.ok) return null;
    const data = (await res.json()) as TurnCost;
    if ((data.cost?.total ?? 0) > 0) {
      return { nano: data.cost.total, estimated: false };
    }
    const est = data.estimated_cost?.total ?? 0;
    if (est > 0) return { nano: est, estimated: true };
    // BYOK 三层价卡全落空：连估算都没有，但确有真实花费——上报未计价而非
    // 静默无值（拍板 2026-07-20，与桌面同口径：显式标注、金额不出数）。
    if (data.cost?.pricing_source === "unpriced") {
      return { nano: 0, estimated: false, unpriced: true };
    }
    return null;
  } catch {
    return null;
  }
}

/** @deprecated Prefer {@link getMessageCostDisplay}; kept for callers that only need billed total. */
export async function getMessageCostTotal(messageId: string): Promise<number> {
  const d = await getMessageCostDisplay(messageId);
  return d && !d.estimated ? d.nano : 0;
}

// --- Account dashboard (设置·用量) ---

export type CostBreakdown = Schemas["CostBreakdown"];
export type UsageBreakdown = Schemas["UsageBreakdown"];
export type UsageWindow = Schemas["UsageWindow"];
export type QuotaStatus = Schemas["QuotaStatus"];
export type RoleCostLine = Schemas["RoleCostLine"];
export type DailyCost = Schemas["DailyCost"];
export type UsageSummary = Schemas["UsageSummary"];

/** Account dashboard: today's tokens/cost, the month's cost, quota + FX rate. */
export async function getUsageSummary(): Promise<UsageSummary> {
  const res = await apiFetch("/v1/usage/summary");
  if (!res.ok) throw new Error(`加载用量失败 (${res.status})`);
  return (await res.json()) as UsageSummary;
}
