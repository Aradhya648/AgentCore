/**
 * Pure cost-derivation helper for the turn cost row (§7.3A). Framework-free on
 * purpose: the money math lives here so it is unit-testable without a DOM, and
 * the components only render the result. (Per-Agent ¥ now shows directly on each
 * graph node from `run.cost`, §7.3B — no payroll split needed.)
 *
 * Money is integer nano-CNY throughout (1 CNY = 1e9). This never re-prices; it
 * only sums already-priced run totals (§7.2：合计以各 run 已定价之和为准).
 * BYOK: billed `total` stays 0; `estimated_total` may carry a community estimate.
 */

export type CostLeaf = {
  total: number;
  estimated_total?: number | null;
  pricing_source?: string | null;
};

export type DisplayMoney = {
  nano: number;
  /** True when showing BYOK estimate (≈), not platform ledger ¥. */
  estimated: boolean;
};

/**
 * The turn cost to display (§7.3A): prefer the authoritative `turnTotal` from
 * `message_end`; when absent (a stopped/crashed turn never gets one) fall back to
 * the sum of the runs that did finish — a lower bound, but it still shows what the
 * team已花. Returns null when there is nothing real to show, so callers render
 * 「—」/ nothing rather than「¥0.00」(§7.5).
 *
 * Note `turnTotal` of 0 is returned verbatim (it is a known total, not "unknown");
 * the caller still gates display on `> 0`.
 */
export function resolveTurnCost(
  turnTotal: number | null,
  runCosts: number[],
): number | null {
  const runTotal = runCosts.reduce((n, c) => n + c, 0);
  return turnTotal ?? (runTotal > 0 ? runTotal : null);
}

/**
 * True when the graph did real work that the platform simply cannot price —
 * some run consumed tokens under `pricing_source=unpriced` (BYOK, 两层价卡全落空).
 * Callers use this to show an explicit「自带密钥·未计价」badge instead of silently
 * omitting the cost segment (which reads as "free"). Zero-usage runs don't count.
 */
export function hasUnpricedUsage(
  runs: Array<
    | {
        cost?: CostLeaf | null;
        usage?: { input: number; output: number } | null;
      }
    | null
    | undefined
  >,
): boolean {
  return runs.some((r) => {
    if (!r?.cost || r.cost.pricing_source !== "unpriced") return false;
    const u = r.usage;
    return u != null && u.input + u.output > 0;
  });
}

/**
 * Turn display money with BYOK estimate awareness: billed total wins; else
 * `estimated_total`; else sum finished runs the same way. Null = nothing to show.
 */
export function resolveTurnDisplayMoney(
  turnCost: CostLeaf | null | undefined,
  runCosts: Array<CostLeaf | null | undefined>,
): DisplayMoney | null {
  if (turnCost) {
    if (turnCost.total > 0) {
      return { nano: turnCost.total, estimated: false };
    }
    const est = turnCost.estimated_total;
    if (est != null && est > 0) return { nano: est, estimated: true };
    // Known zero (platform free / unpriced) — caller gates on nano > 0.
    return { nano: 0, estimated: false };
  }
  let billed = 0;
  let estimated = 0;
  for (const c of runCosts) {
    if (!c) continue;
    billed += c.total ?? 0;
    estimated += c.estimated_total ?? 0;
  }
  if (billed > 0) return { nano: billed, estimated: false };
  if (estimated > 0) return { nano: estimated, estimated: true };
  return null;
}
