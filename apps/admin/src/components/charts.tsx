import { cn, fmtCny, mmdd, nanoUsdToCny } from "@/lib/utils";
import type { DailyTurns } from "@/services/adminObservability";
import type { DailyCost } from "@/services/adminUsage";

/**
 * Shared 7-day trend bars for the admin console (用量 / 用户详情 / 概览 all show the
 * same cost sparkline; 观测 / 概览 share the turn one). Kept presentational and
 * dependency-light so every surface renders an identical chart instead of drifting.
 */
export function CostTrendBars({
  data,
  cnyPerUsd,
}: {
  data: DailyCost[];
  cnyPerUsd: number;
}) {
  const max = Math.max(1, ...data.map((d) => d.cost_total));
  return (
    <div className="flex items-end gap-2">
      {data.map((d) => {
        const pct = (d.cost_total / max) * 100;
        const cny = nanoUsdToCny(d.cost_total, cnyPerUsd);
        return (
          <div key={d.date} className="flex flex-1 flex-col items-center gap-2">
            <div className="flex h-28 w-full items-end">
              <div
                className="w-full rounded-t-md bg-primary/80"
                style={{ height: `${Math.max(pct, 2)}%` }}
                title={`${d.date} · ${fmtCny(cny)}`}
              />
            </div>
            <span className="text-muted-foreground text-xs tabular-nums">
              {mmdd(d.date)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** 7-day turn bars with the error segment stacked (destructive) atop the ok segment. */
export function TurnTrendBars({ data }: { data: DailyTurns[] }) {
  const max = Math.max(1, ...data.map((d) => d.turns));
  return (
    <div className="flex items-end gap-2">
      {data.map((d) => {
        const okPct = (Math.max(d.turns - d.errors, 0) / max) * 100;
        const errPct = (d.errors / max) * 100;
        return (
          <div key={d.date} className="flex flex-1 flex-col items-center gap-2">
            <div
              className="flex h-28 w-full flex-col justify-end"
              title={`${d.date} · 回合 ${d.turns} · 错误 ${d.errors}`}
            >
              {d.errors > 0 && (
                <div
                  className="w-full rounded-t-md bg-destructive/80"
                  style={{ height: `${Math.max(errPct, 2)}%` }}
                />
              )}
              <div
                className={cn(
                  "w-full bg-primary/80",
                  d.errors > 0 ? "" : "rounded-t-md",
                )}
                style={{ height: `${Math.max(okPct, d.turns > 0 ? 2 : 0)}%` }}
              />
            </div>
            <span className="text-muted-foreground text-xs tabular-nums">
              {mmdd(d.date)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
