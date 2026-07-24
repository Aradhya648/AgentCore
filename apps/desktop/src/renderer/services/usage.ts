import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

/**
 * Cost & usage REST surface — the read side of the「团队工资单 / 账户仪表盘」
 * (§三 / §七).
 *
 * The REST types below are GENERATED from the backend OpenAPI spec
 * (`types/api.generated.ts`, via `pnpm gen:api`), so they track `api/schemas.py`
 * automatically with zero hand-written drift — this file is the reference slice
 * for that codegen migration (API 开发规范). Money is always integer nano-USD
 * (1 USD = 1e9) and the server attaches the display CNY value so the client never
 * re-prices.
 *
 * The ledger (`cost_events`) is the truth source for spend, so these reads replay
 * a past turn's payroll on reload (the streamed `run_completed.cost` /
 * `message_end.cost` light them up live).
 */

type Schemas = components["schemas"];

/** Token counts (cache_hit + cache_miss == input; reasoning ⊆ output). */
export type UsageBreakdown = Schemas["UsageBreakdown"];
/** A cost in integer nano-USD plus the server-computed CNY display value. */
export type CostBreakdown = Schemas["CostBreakdown"];
/** One participant's row in the team payroll (one Run = one Agent). */
export type AgentCostLine = Schemas["AgentCostLine"];
/** A turn's cost + per-Agent payroll (`GET /v1/messages/{id}/cost`, 工资单). */
export type TurnCost = Schemas["TurnCost"];
/** Aggregated usage over a time window (today / month). */
export type UsageWindow = Schemas["UsageWindow"];
/** Free-tier limits (决策④); 0 = unlimited. Money is USD nano internally. */
export type QuotaStatus = Schemas["QuotaStatus"];
/** One role's monthly spend — the team payroll grouped by role (本月各角色花销). */
export type RoleCostLine = Schemas["RoleCostLine"];
/** One UTC day's total spend — a point in the dashboard 7-day trend sparkline. */
export type DailyCost = Schemas["DailyCost"];
/** Account dashboard payload (`GET /v1/usage/summary`). */
export type UsageSummary = Schemas["UsageSummary"];

/** Account dashboard: today's tokens/cost, the month's cost, the quota + FX. */
export function getUsageSummary(): Promise<UsageSummary> {
  return api.get<UsageSummary>("/v1/usage/summary");
}

/** The team payroll for one assistant turn (工资单), rebuilt from the ledger. */
export function getMessageCost(messageId: string): Promise<TurnCost> {
  return api.get<TurnCost>(`/v1/messages/${messageId}/cost`);
}
