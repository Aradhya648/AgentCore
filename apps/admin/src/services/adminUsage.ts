import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

export type AdminUsageSummary = components["schemas"]["AdminUsageSummary"];
export type AdminUserCostLine = components["schemas"]["AdminUserCostLine"];
export type ModelCostLine = components["schemas"]["ModelCostLine"];
export type UsageWindow = components["schemas"]["UsageWindow"];
export type DailyCost = components["schemas"]["DailyCost"];

/**
 * 全站用量看板: platform-wide today/month totals, the Top spenders by user
 * (工资单 by user), and the 7-day platform trend — the cross-user counterpart of
 * the per-user `/v1/usage/summary`.
 */
export async function fetchUsageSummary(): Promise<AdminUsageSummary> {
  return api.get<AdminUsageSummary>("/v1/admin/usage/summary");
}
