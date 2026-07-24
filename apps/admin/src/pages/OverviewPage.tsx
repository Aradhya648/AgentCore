import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtCny, fmtInt, fmtMs, fmtTime } from "@/lib/utils";
import type { TurnMetricLine } from "@/services/adminObservability";
import { type AdminOverview, fetchOverview } from "@/services/adminOverview";
import { errorMessage } from "@/services/api";
import { ChevronRight, RefreshCw } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/** A 0..1 fraction as a 1-decimal percentage (e.g. 0.042 → "4.2%"). */
function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

/** Recent errors preview shows only the freshest few — the full feed lives in 分析·健康. */
const ERROR_PREVIEW_LIMIT = 5;

/**
 * 概览: the console's landing hub. It surfaces today's pulse as summary tiles +
 * a deployment-health strip + a short recent-errors preview, each one a *link*
 * into the single page that owns the detail (分析 / 用户 / 系统). It deliberately
 * does not re-render the full charts/tables those pages own.
 */
export function OverviewPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const openReplay = (conversationId: string) => {
    navigate(`/replay/${conversationId}`, { state: { from: location.pathname } });
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchOverview());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const today = data?.today;
  const errTone =
    !today || today.errors === 0
      ? "success"
      : today.error_rate <= 0.05
        ? "warning"
        : "destructive";
  const byok = data?.billing_mode === "byok";

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">概览</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            平台此刻 · 今日活跃 / 成本 / 回合健康 + 部署状态（点卡片进对应详情）
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
          aria-label="刷新"
        >
          <RefreshCw size={14} className={cn(loading && "animate-spin")} />
        </Button>
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 rounded-xl border border-border bg-card py-16 text-muted-foreground text-sm">
          <Spinner />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card py-16 text-sm">
          <span className="text-destructive">{error}</span>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            重试
          </Button>
        </div>
      )}

      {!loading && !error && data && today && (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <MetricCard
              label="今日活跃用户"
              value={fmtInt(data.active_users_today)}
              sub={`共 ${fmtInt(data.users_active)} 活跃账号`}
              onClick={() => navigate("/users")}
            />
            <MetricCard
              label="今日回合"
              value={fmtInt(today.turns)}
              badge={
                <Badge tone={errTone}>
                  错误 {fmtInt(today.errors)} · {fmtPct(today.error_rate)}
                </Badge>
              }
              onClick={() => navigate("/analytics/health")}
            />
            <MetricCard
              label="今日成本"
              value={fmtCny(data.cost_today.cny_total)}
              onClick={() => navigate("/analytics/cost")}
            />
            <MetricCard
              label="P95 延迟"
              value={fmtMs(today.p95_duration_ms)}
              sub={`平均 ${today.avg_rounds.toFixed(1)} 轮 · 委派 ${fmtPct(today.delegated_rate)}`}
              onClick={() => navigate("/analytics/health")}
            />
          </div>

          <button
            type="button"
            onClick={() => navigate("/system")}
            className="flex flex-wrap items-center gap-x-8 gap-y-3 rounded-xl border border-border bg-card px-5 py-4 text-left text-sm outline-none transition-colors hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">数据库</span>
              <Badge tone={data.database_ok ? "success" : "destructive"}>
                {data.database_ok ? "正常" : "不可达"}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">计费模式</span>
              <Badge tone="primary">{byok ? "BYOK · 自带 Key" : "平台付费"}</Badge>
            </div>
            <span className="ml-auto inline-flex items-center gap-0.5 text-muted-foreground text-xs">
              系统状态
              <ChevronRight size={14} />
            </span>
          </button>

          <ErrorsPreview
            rows={data.recent_errors}
            onOpen={openReplay}
            onViewAll={() => navigate("/analytics/health")}
          />
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  badge,
  onClick,
}: {
  label: string;
  value: string;
  sub?: string;
  badge?: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-xl border border-border bg-card p-5 text-left outline-none transition-colors hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted-foreground text-sm">{label}</span>
        {badge}
      </div>
      <div className="mt-1 text-2xl font-semibold text-foreground tabular-nums">
        {value}
      </div>
      {sub && <div className="mt-2 text-muted-foreground text-xs">{sub}</div>}
    </button>
  );
}

function ErrorsPreview({
  rows,
  onOpen,
  onViewAll,
}: {
  rows: TurnMetricLine[];
  onOpen: (conversationId: string) => void;
  onViewAll: () => void;
}) {
  const preview = rows.slice(0, ERROR_PREVIEW_LIMIT);
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-4 border-border border-b px-5 py-3.5">
        <div>
          <h2 className="text-base font-semibold text-foreground">近期错误</h2>
          <p className="mt-0.5 text-muted-foreground text-xs">
            最近失败的回合 · 点击行进入会话复盘
          </p>
        </div>
        <button
          type="button"
          onClick={onViewAll}
          className="inline-flex shrink-0 items-center gap-0.5 rounded text-muted-foreground text-xs outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          查看全部
          <ChevronRight size={14} />
        </button>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <th className="px-5 py-2.5 font-medium">时间</th>
            <th className="px-5 py-2.5 font-medium">结束原因</th>
            <th className="px-5 py-2.5 font-medium">错误</th>
            <th className="px-5 py-2.5 text-right font-medium">耗时</th>
          </tr>
        </thead>
        <tbody>
          {preview.map((row) => (
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
            </tr>
          ))}
        </tbody>
      </table>
      {preview.length === 0 && (
        <div className="py-10 text-center text-muted-foreground text-sm">
          近期暂无错误回合
        </div>
      )}
    </section>
  );
}
