import { CostTrendBars, TurnTrendBars } from "@/components/charts";
import { AuditSummaryWidget } from "@/components/AuditSummaryWidget";
import { CopyableId } from "@/components/CopyableId";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import {
  cn,
  COST_ESTIMATE_HINT,
  fmtCny,
  fmtCompact,
  fmtEstimatedCny,
  fmtInt,
  fmtMs,
  fmtNanoCny,
  fmtTime,
  nanoUsdToCny,
} from "@/lib/utils";
import {
  type AdminObservabilitySummary,
  type TurnHealthWindow,
  type TurnMetricLine,
  fetchObservabilitySummary,
} from "@/services/adminObservability";
import {
  type AdminUsageSummary,
  type ModelCostLine,
  type UsageWindow,
  fetchUsageSummary,
} from "@/services/adminUsage";
import { errorMessage } from "@/services/api";
import { Info, RefreshCw } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";

/** The two lenses 分析 fuses: 成本 (money) and 健康 (reliability). */
export type AnalyticsSegment = "cost" | "health";

/** A 0..1 fraction as a 1-decimal percentage (e.g. 0.042 → "4.2%"). */
function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

/**
 * 分析: the merged platform-wide reporting page (former 用量 + 观测). The two
 * lenses share the same skeleton (window cards + 7-day trend + table + 会话复盘
 * drill-in), so they live behind one segmented control instead of two tabs. Only
 * the active lens fetches, so switching is a fresh load, not a double request.
 */
export function AnalyticsPage() {
  const { segment: segmentParam } = useParams<{ segment: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [idInput, setIdInput] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [costLoading, setCostLoading] = useState(false);
  const [healthLoading, setHealthLoading] = useState(false);

  if (segmentParam !== "cost" && segmentParam !== "health") {
    return <Navigate to="/analytics/cost" replace />;
  }

  const segment: AnalyticsSegment = segmentParam;

  const openReplay = (conversationId: string) => {
    navigate(`/replay/${conversationId}`, { state: { from: location.pathname } });
  };

  const submitReplay = (e: FormEvent) => {
    e.preventDefault();
    const id = idInput.trim();
    if (id) openReplay(id);
  };

  const setSegment = (s: AnalyticsSegment) => navigate(`/analytics/${s}`);

  const activeLoading = segment === "cost" ? costLoading : healthLoading;
  const subtitle =
    segment === "cost"
      ? "跨用户聚合 · 今日 / 本月成本、按模型 / 角色拆分、Top 花销用户、近 7 日趋势"
      : "跨用户聚合 · 回合健康（错误率 / P95 延迟 / 委派率 / 协作质量）、近 7 日趋势、近期错误";

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">分析</h1>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        </div>
        <div className="flex items-center gap-2">
          <SegmentToggle value={segment} onChange={setSegment} />
          <form onSubmit={submitReplay} className="flex items-center gap-2">
            <Input
              value={idInput}
              onChange={(e) => setIdInput(e.target.value)}
              placeholder="会话 ID 复盘…"
              className="w-48"
            />
            <Button
              type="submit"
              variant="outline"
              size="sm"
              disabled={!idInput.trim()}
            >
              复盘
            </Button>
          </form>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((k) => k + 1)}
            disabled={activeLoading}
            aria-label="刷新"
          >
            <RefreshCw size={14} className={cn(activeLoading && "animate-spin")} />
          </Button>
        </div>
      </div>

      {segment === "cost" ? (
        <CostPanel reloadKey={reloadKey} onLoadingChange={setCostLoading} />
      ) : (
        <HealthPanel
          reloadKey={reloadKey}
          onLoadingChange={setHealthLoading}
          onOpenReplay={openReplay}
        />
      )}
    </div>
  );
}

function SegmentToggle({
  value,
  onChange,
}: {
  value: AnalyticsSegment;
  onChange: (s: AnalyticsSegment) => void;
}) {
  const items: { id: AnalyticsSegment; label: string }[] = [
    { id: "cost", label: "成本" },
    { id: "health", label: "健康" },
  ];
  return (
    <div className="inline-flex items-center rounded-lg border border-border p-0.5">
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          aria-pressed={value === it.id}
          onClick={() => onChange(it.id)}
          className={cn(
            "h-7 rounded-lg px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
            value === it.id
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

function PanelState({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 rounded-xl border border-border bg-card py-16 text-muted-foreground text-sm">
        <Spinner />
        加载中…
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card py-16 text-sm">
      <span className="text-destructive">{error}</span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}

function CostPanel({
  reloadKey,
  onLoadingChange,
}: {
  reloadKey: number;
  onLoadingChange: (loading: boolean) => void;
}) {
  const [data, setData] = useState<AdminUsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    onLoadingChange(true);
    setError(null);
    try {
      setData(await fetchUsageSummary());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      onLoadingChange(false);
    }
  }, [onLoadingChange]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  if (loading || error || !data) {
    return <PanelState loading={loading} error={error} onRetry={() => void load()} />;
  }

  const byok = data.billing_mode === "byok";

  return (
    <div className="flex flex-col gap-5">
      {byok && (
        <div className="flex items-start gap-2.5 rounded-xl border border-border bg-muted/40 px-4 py-3 text-sm text-muted-foreground">
          <Info size={16} className="mt-0.5 shrink-0 text-primary" />
          <span>
            当前为 <strong className="text-foreground">BYOK（自带 Key）</strong>
            模式：记账成本恒为 0；下方「估算」列为按社区价目的 ≈¥，
            非上游账单。
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <CostWindowCard label="今日" window={data.today} byok={byok} />
        <CostWindowCard label="本月" window={data.month} byok={byok} />
      </div>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-base font-semibold text-foreground">
          近 7 日成本趋势
        </h2>
        <CostTrendBars data={data.recent_daily_cost} cnyPerUsd={data.cny_per_usd} />
      </section>

      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="border-border border-b px-5 py-3.5">
          <h2 className="text-base font-semibold text-foreground">
            本月各模型用量
          </h2>
          <p className="mt-0.5 text-muted-foreground text-xs">
            全站按 call 明细聚合（cost_calls · 成本降序）
            {byok ? ` · ${COST_ESTIMATE_HINT}` : ""}
          </p>
        </div>
        {data.month_by_model.length === 0 ? (
          <p className="px-5 py-8 text-center text-muted-foreground text-sm">
            本月暂无模型调用记录
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
                <th className="px-5 py-2.5 font-medium">模型</th>
                <th className="px-5 py-2.5 text-right font-medium">调用次数</th>
                <th className="px-5 py-2.5 text-right font-medium">Tokens</th>
                <th className="px-5 py-2.5 text-right font-medium">本月成本</th>
                <th className="px-5 py-2.5 text-right font-medium">估算</th>
              </tr>
            </thead>
            <tbody>
              {data.month_by_model.map((row: ModelCostLine) => (
                <tr
                  key={row.model}
                  className="border-border border-b last:border-0 hover:bg-accent/40"
                >
                  <td className="px-5 py-3 font-medium text-foreground">
                    {row.model || "（未标注）"}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                    {fmtInt(row.calls)}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                    {fmtCompact(row.tokens_total)}
                  </td>
                  <td className="px-5 py-3 text-right font-medium text-foreground tabular-nums">
                    {fmtNanoCny(row.cost_total, data.cny_per_usd)}
                  </td>
                  <td
                    className="px-5 py-3 text-right text-muted-foreground tabular-nums"
                    title={
                      row.cost_estimated_total > 0
                        ? COST_ESTIMATE_HINT
                        : undefined
                    }
                  >
                    {fmtNanoCny(
                      row.cost_estimated_total,
                      data.cny_per_usd,
                      true,
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="overflow-hidden rounded-xl border border-border bg-card">
        <div className="border-border border-b px-5 py-3.5">
          <h2 className="text-base font-semibold text-foreground">
            本月 Top 花销用户
          </h2>
          <p className="mt-0.5 text-muted-foreground text-xs">
            按本月成本降序，仅列有花销的账号
          </p>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <th className="px-5 py-2.5 font-medium">#</th>
              <th className="px-5 py-2.5 font-medium">用户</th>
              <th className="px-5 py-2.5 text-right font-medium">本月成本</th>
              <th className="px-5 py-2.5 text-right font-medium">回合数</th>
            </tr>
          </thead>
          <tbody>
            {data.month_by_user.map((row, i) => (
              <tr
                key={row.user_id}
                className="border-border border-b last:border-0 hover:bg-accent/40"
              >
                <td className="px-5 py-3 text-muted-foreground tabular-nums">
                  {i + 1}
                </td>
                <td className="px-5 py-3">
                  <div className="font-medium text-foreground">
                    {row.display_name || row.username}
                  </div>
                  <div className="text-muted-foreground text-xs">
                    @{row.username}
                  </div>
                </td>
                <td className="px-5 py-3 text-right font-medium text-foreground tabular-nums">
                  {fmtCny(nanoUsdToCny(row.cost_total, data.cny_per_usd))}
                </td>
                <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                  {fmtInt(row.turns)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.month_by_user.length === 0 && (
          <div className="py-10 text-center text-muted-foreground text-sm">
            本月暂无花销记录
          </div>
        )}
      </section>
    </div>
  );
}

function CostWindowCard({
  label,
  window,
  byok,
}: {
  label: string;
  window: UsageWindow;
  byok: boolean;
}) {
  const est = window.estimated_cost;
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="text-muted-foreground text-sm">
        {byok ? `${label}估算` : `${label}总成本`}
      </div>
      <div
        className="mt-1 text-2xl font-semibold text-foreground tabular-nums"
        title={byok && est ? COST_ESTIMATE_HINT : undefined}
      >
        {byok
          ? fmtEstimatedCny(est?.cny_total ?? 0)
          : fmtCny(window.cost.cny_total)}
      </div>
      <div className="mt-4 flex items-center gap-6 text-sm">
        <Stat
          label="Token"
          value={fmtCompact(window.usage.input + window.usage.output)}
        />
        <Stat label="请求" value={fmtInt(window.requests)} />
      </div>
    </div>
  );
}

function HealthPanel({
  reloadKey,
  onLoadingChange,
  onOpenReplay,
}: {
  reloadKey: number;
  onLoadingChange: (loading: boolean) => void;
  onOpenReplay: (conversationId: string) => void;
}) {
  const [data, setData] = useState<AdminObservabilitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    onLoadingChange(true);
    setError(null);
    try {
      setData(await fetchObservabilitySummary());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      onLoadingChange(false);
    }
  }, [onLoadingChange]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  if (loading || error || !data) {
    return <PanelState loading={loading} error={error} onRetry={() => void load()} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <HealthCard label="今日" window={data.today} />
        <HealthCard label="近 7 日" window={data.week} />
      </div>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="mb-4 text-base font-semibold text-foreground">
          近 7 日回合趋势
        </h2>
        <TurnTrendBars data={data.recent_daily} />
      </section>

      <AuditSummaryWidget reloadKey={reloadKey} />

      <ErrorsTable rows={data.recent_errors} onOpen={onOpenReplay} />
    </div>
  );
}

function HealthCard({
  label,
  window,
}: {
  label: string;
  window: TurnHealthWindow;
}) {
  // 0 = clean, ≤5% = watch, above = problem — frames the error rate's color.
  const errTone =
    window.errors === 0
      ? "success"
      : window.error_rate <= 0.05
        ? "warning"
        : "destructive";
  // 协作质量 (学·度量 §2.5): the four MAST-labeled signals only mean something once a turn
  // delegated — survival rate is share-of-delegated, the rest are window sums over members.
  const hasDelegated = window.delegated_turns > 0;
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-baseline justify-between">
        <div className="text-muted-foreground text-sm">{label}回合数</div>
        <Badge tone={errTone}>
          错误 {fmtInt(window.errors)} · {fmtPct(window.error_rate)}
        </Badge>
      </div>
      <div className="mt-1 text-2xl font-semibold text-foreground tabular-nums">
        {fmtInt(window.turns)}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-4 text-sm">
        <Stat label="P95 延迟" value={fmtMs(window.p95_duration_ms)} />
        <Stat label="平均轮数" value={window.avg_rounds.toFixed(1)} />
        <Stat label="委派率" value={fmtPct(window.delegated_rate)} />
      </div>
      <div className="mt-4 border-border border-t pt-4">
        <div className="mb-2.5 text-muted-foreground text-xs">
          协作质量 · MAST（委派 {fmtInt(window.delegated_turns)} 回合）
        </div>
        <div className="grid grid-cols-4 gap-4 text-sm">
          <Stat
            label="首计划存活"
            value={hasDelegated ? fmtPct(window.first_plan_survival_rate) : "—"}
            hint="［规格］委派回合中，首个计划未被监督边界（让出 / 改判）打断、一气跑到底的占比 —— 越高越好"
          />
          <Stat
            label="漂移"
            value={hasDelegated ? fmtInt(window.scope_signals) : "—"}
            hint="［错位］worker 越界（scope）升级次数 —— 越低越好"
          />
          <Stat
            label="返工"
            value={hasDelegated ? fmtInt(window.revises) : "—"}
            hint="［验证］队长定向唤回（revise）次数 —— 越低越好"
          />
          <Stat
            label="升级"
            value={hasDelegated ? fmtInt(window.escalations) : "—"}
            hint="worker → 队长 升级信号总数（协作信号）"
          />
        </div>
      </div>
    </div>
  );
}

function ErrorsTable({
  rows,
  onOpen,
}: {
  rows: TurnMetricLine[];
  onOpen: (conversationId: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="border-border border-b px-5 py-3.5">
        <h2 className="text-base font-semibold text-foreground">近期错误</h2>
        <p className="mt-0.5 text-muted-foreground text-xs">
          最近失败的回合（newest-first）· 点击行进入会话复盘
        </p>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <th className="px-5 py-2.5 font-medium">时间</th>
            <th className="px-5 py-2.5 font-medium">结束原因</th>
            <th className="px-5 py-2.5 font-medium">错误</th>
            <th className="px-5 py-2.5 text-right font-medium">耗时</th>
            <th className="px-5 py-2.5 font-medium">trace</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.turn_id}
              onClick={() => onOpen(row.conversation_id)}
              className="cursor-pointer border-border border-b align-top last:border-0 hover:bg-accent/40"
            >
              <td className="whitespace-nowrap px-5 py-3 text-muted-foreground tabular-nums">
                {fmtTime(row.created_at)}
              </td>
              <td className="px-5 py-3">
                <Badge tone="destructive">{row.finish_reason ?? "error"}</Badge>
              </td>
              <td className="max-w-md px-5 py-3 text-foreground">
                <span className="line-clamp-2 break-words">{row.error ?? "—"}</span>
              </td>
              <td className="whitespace-nowrap px-5 py-3 text-right text-muted-foreground tabular-nums">
                {fmtMs(row.duration_ms)}
              </td>
              <td className="px-5 py-3">
                {row.trace_id ? (
                  <CopyableId
                    value={row.trace_id}
                    label="trace_id"
                    display={row.trace_id.slice(0, 8)}
                    titleHint={`${row.trace_id}（点击复制，用于 grep logs/dev.jsonl）`}
                  />
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="py-10 text-center text-muted-foreground text-sm">
          近期暂无错误回合
        </div>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div title={hint}>
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="mt-0.5 font-medium text-foreground tabular-nums">{value}</div>
    </div>
  );
}
