import { Button, Card, IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useLlmProviders } from "@/hooks/useLlmProviders";
import { agentColorVar } from "@/lib/agentIdentity";
import {
  formatCompact,
  formatCost,
  formatDisplayCost,
  formatUsd,
} from "@/lib/format";
import { useUsageStore } from "@/stores/usage";
import { KeyRound, Loader2, RefreshCw } from "lucide-react";
import { useEffect } from "react";
import { SettingsHeader } from "./SettingsHeader";

/**
 * Account usage dashboard (§7.3D) — the manager's view of the team's spend.
 *
 * 大众面 leads with two semantic quota meters (本月额度 / 今日 tokens) so the user
 * reads「还剩多少」at a glance without big raw numbers. Token / cost breakdown and
 * run-detail「资源消耗」default-expand are always on. All numbers come from
 * `GET /usage/summary` via the usage store; money formats off the single server FX rate.
 * Free-tier users (`free_tier_active`) relabel the monthly meter; BYOK-with-key shows
 * token meters + ≈¥ estimates when `estimated_cost` / `cost_estimated_total` is present.
 */
export function UsageSettings() {
  const summary = useUsageStore((s) => s.summary);
  const loading = useUsageStore((s) => s.loading);
  const error = useUsageStore((s) => s.error);
  const cnyPerUsd = useUsageStore((s) => s.cnyPerUsd);
  const fetchSummary = useUsageStore((s) => s.fetchSummary);
  const { data: llmProviders } = useLlmProviders();
  const freeTierActive = llmProviders?.free_tier_active === true;

  // Refresh on open: the bootstrap snapshot may be stale by the time the user
  // lands here. Best-effort (the store keeps the last value + a soft error).
  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  const refresh = () => void fetchSummary();
  // BYOK with a configured key: platform quota is dormant. Free-tier (no key)
  // must NOT take this branch — they see platform meters with a free-tier label.
  const byok = summary?.billing_mode === "byok" && !freeTierActive;

  return (
    <div>
      <SettingsHeader
        title="用量"
        description={
          byok
            ? "自带 Key 模式：平台不限额。有估算价时显示 ≈¥（非上游账单），并以 token 用量为主。"
            : freeTierActive
              ? "本月免费额度与今日用量。额度用完可接入自己的模型继续。"
              : "本月额度与今日用量。成本按团队角色拆分，以人民币展示。"
        }
        action={
          // Manual refresh once data exists — numbers go stale after running tasks
          // elsewhere (mount-only fetch otherwise). First load / first-load failure
          // are handled by the dedicated states below, so the button shows here.
          summary ? (
            <SimpleTooltip label="刷新">
              <IconButton
                size="md"
                aria-label="刷新"
                onClick={refresh}
                disabled={loading}
              >
                <RefreshCw
                  size={16}
                  className={loading ? "animate-spin" : undefined}
                />
              </IconButton>
            </SimpleTooltip>
          ) : undefined
        }
      />

      {/* 三态分离：已有数据（含刷新失败的软告警）/ 首屏失败 / 首屏加载中。 */}
      {summary ? (
        <>
          {error && <RefreshErrorBanner message={error} onRetry={refresh} />}
          <Dashboard
            summary={summary}
            cnyPerUsd={cnyPerUsd}
            byok={byok}
            freeTierActive={freeTierActive}
          />
        </>
      ) : error ? (
        <ErrorState message={error} onRetry={refresh} />
      ) : (
        <LoadingState />
      )}
    </div>
  );
}

/** First-load spinner — distinct from the error state (P1: 加载/错误分离). */
function LoadingState() {
  return (
    <div className="mt-6 flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 size={16} className="animate-spin" />
      加载中…
    </div>
  );
}

/** First-load failure: no data to show, so a prominent centered retry (P1). */
function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <Card className="mt-6 flex flex-col items-center justify-center gap-3 border-dashed py-16 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
      <Button onClick={onRetry}>重试</Button>
    </Card>
  );
}

/**
 * Refresh failed but stale data exists: a soft amber banner above the dashboard
 * with an inline retry. 用量是附属呈现——刷新失败不清空已有数字 (P1)，只提示可能过期。
 */
function RefreshErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <Card className="mt-6 flex items-center justify-between gap-3 border-destructive/40 bg-destructive/10 px-4 py-2.5">
      <p className="text-xs text-destructive">{message}</p>
      <Button variant="neutral" onClick={onRetry}>
        重试
      </Button>
    </Card>
  );
}

function Dashboard({
  summary,
  cnyPerUsd,
  byok,
  freeTierActive,
}: {
  summary: Summary;
  cnyPerUsd: number;
  byok: boolean;
  freeTierActive: boolean;
}) {
  const { today, month, quota } = summary;
  const monthLimit = quota.monthly_cost_nano;
  const monthUsed = month.cost.total;
  const dayCostLimit = quota.daily_cost_nano;
  const dayCostUsed = today.cost.total;
  const dayTokenLimit = quota.daily_tokens;
  const dayTokensUsed = today.usage.input + today.usage.output;
  const dayReqLimit = quota.daily_requests;
  const dayReqUsed = today.requests;
  const monthNear = monthLimit > 0 && monthUsed / monthLimit >= 0.8;
  const monthLabel = freeTierActive ? "本月免费额度" : "本月额度";

  // Reset captions derive from the backend's UTC window boundaries (usage.py /
  // quota.py) rendered in local time — see resetTexts() for why.
  const { dailyResetText, monthlyResetText } = resetTexts();

  const moneyCaption =
    monthLimit > 0
      ? `已用 ${formatCost(monthUsed, cnyPerUsd)} / ${formatCost(monthLimit, cnyPerUsd)} · ${monthlyResetText}`
      : `已用 ${formatCost(monthUsed, cnyPerUsd)} · 不限`;
  // 单日成本 backstop (F2) — only surfaced when a daily cost cap is configured
  // (platform flip); byok / free-tier deployments leave it 0 and this meter hides.
  const dayCostCaption = `已用 ${formatCost(dayCostUsed, cnyPerUsd)} / ${formatCost(dayCostLimit, cnyPerUsd)} · ${dailyResetText}`;
  const tokenCaption =
    dayTokenLimit > 0
      ? `${formatCompact(dayTokensUsed)} / ${formatCompact(dayTokenLimit)} · ${dailyResetText}`
      : `${formatCompact(dayTokensUsed)} · 不限`;
  const reqCaption =
    dayReqLimit > 0
      ? `${dayReqUsed} / ${dayReqLimit} 次 · ${dailyResetText}`
      : `${dayReqUsed} 次 · 不限`;

  return (
    <div className="mt-6 space-y-5">
      {byok ? (
        <>
          <ByokNote />
          <QuotaMeter
            label="今日 tokens"
            used={dayTokensUsed}
            limit={dayTokenLimit}
            caption={tokenCaption}
          />
        </>
      ) : (
        <>
          <QuotaMeter
            label={monthLabel}
            used={monthUsed}
            limit={monthLimit}
            caption={moneyCaption}
          />
          {monthNear && (
            <p className="-mt-3 text-xs text-destructive">
              {freeTierActive
                ? "接近本月免费额度，用完后请接入自己的模型继续。"
                : "接近本月额度，用完可联系管理员提额，或接入自己的 key 继续。"}
            </p>
          )}
          {dayCostLimit > 0 && (
            <QuotaMeter
              label="今日额度"
              used={dayCostUsed}
              limit={dayCostLimit}
              caption={dayCostCaption}
            />
          )}
          <QuotaMeter
            label="今日 tokens"
            used={dayTokensUsed}
            limit={dayTokenLimit}
            caption={tokenCaption}
          />
          <QuotaMeter
            label="今日请求"
            used={dayReqUsed}
            limit={dayReqLimit}
            caption={reqCaption}
          />
        </>
      )}

      {/* 近 7 日成本趋势 (§7.3D) — ¥ over time, 大众-visible. Hidden when the whole
          window had no spend (a flat zero trend tells the user nothing). */}
      {summary.recent_daily_cost.some((p) => p.cost_total > 0) && !byok && (
        <CostTrend points={summary.recent_daily_cost} cnyPerUsd={cnyPerUsd} />
      )}

      {/* 本月各角色花销 (§7.3D, 团队工资单 by role) — platform ¥ always;
          BYOK shows ≈¥ when cost_estimated_total > 0. */}
      {summary.month_by_role.length > 0 &&
        (!byok ||
          summary.month_by_role.some((l) => l.cost_estimated_total > 0)) && (
          <RolePayroll
            lines={summary.month_by_role}
            cnyPerUsd={cnyPerUsd}
            estimated={byok}
          />
        )}

      <UsageDetail summary={summary} cnyPerUsd={cnyPerUsd} byok={byok} />
    </div>
  );
}

type Summary = NonNullable<
  ReturnType<typeof useUsageStore.getState>["summary"]
>;

/**
 * BYOK reframe of the quota block: the platform额度 is dormant (the turn runs on
 * the user's own DeepSeek key), so instead of meters we explain that spend below
 * is the user's own estimated DeepSeek cost and there is no platform cap.
 */
function ByokNote() {
  return (
    <Card
      variant="muted"
      className="flex items-start gap-2.5 bg-muted/30 px-4 py-3"
    >
      <KeyRound size={16} className="mt-0.5 shrink-0 text-muted-foreground" />
      <p className="text-xs text-muted-foreground">
        当前为「自带 Key」模式：对话走你配置的模型与端点，平台不设上限。下方以
        token 为主；有估算价时显示 ≈¥（按社区价目/自填单价，非上游账单）。
      </p>
    </Card>
  );
}

/**
 * Reset captions for the quota meters, derived from the backend's UTC window
 * boundaries (usage.py / quota.py) and rendered in the user's LOCAL time.
 *
 * Daily windows reset at the next UTC midnight, the monthly window at the next UTC
 * month start — both the same instant-of-day in local time (the UTC offset). So the
 * daily caption is that recurring local time and the monthly caption is the local
 * date + that time. Building the date from the UTC boundary (not a local-midnight
 * `new Date(y, m+1, 1)`) is what fixes the prior reset label drifting by the offset
 * (per-user timezone windows are a later backend refinement).
 */
function resetTexts(): { dailyResetText: string; monthlyResetText: string } {
  const now = new Date();
  const dailyReset = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1),
  );
  const monthlyReset = new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1),
  );
  const pad = (n: number) => String(n).padStart(2, "0");
  const hhmm = `${pad(dailyReset.getHours())}:${pad(dailyReset.getMinutes())}`;
  return {
    dailyResetText: `每日 ${hhmm} 重置`,
    monthlyResetText: `${monthlyReset.getMonth() + 1} 月 ${monthlyReset.getDate()} 日 ${hhmm} 重置`,
  };
}

/** A semantic quota bar: % filled, amber past 80%, no bar when unlimited (§7.3D). */
function QuotaMeter({
  label,
  used,
  limit,
  caption,
}: {
  label: string;
  used: number;
  limit: number;
  caption: string;
}) {
  const unlimited = limit <= 0;
  const pct = unlimited ? 0 : Math.min(Math.round((used / limit) * 100), 100);
  const near = !unlimited && pct >= 80;

  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-foreground">{label}</span>
        <span className={near ? "text-destructive" : "text-muted-foreground"}>
          {unlimited ? "不限" : `${pct}%`}
        </span>
      </div>
      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-muted">
        {!unlimited && (
          <div
            className={`h-full rounded-full ${near ? "bg-destructive" : "bg-primary"}`}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{caption}</p>
    </div>
  );
}

/** Zh weekday for an ISO UTC date — read in UTC so the label matches the day key
 * (the backend buckets by UTC calendar day), tz-offset-proof. */
function weekdayLabel(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  return `周${["日", "一", "二", "三", "四", "五", "六"][d.getUTCDay()]}`;
}

/**
 * 近 7 日成本趋势 (§7.3D) — a compact daily-spend bar sparkline. Bars scale to the
 * window's max day; ¥ per day on hover. Money over time is 大众-visible (§7.1).
 */
function CostTrend({
  points,
  cnyPerUsd,
}: {
  points: Summary["recent_daily_cost"];
  cnyPerUsd: number;
}) {
  const max = points.reduce((m, p) => Math.max(m, p.cost_total), 0);
  const total = points.reduce((s, p) => s + p.cost_total, 0);
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <p className="text-sm text-foreground">近 7 日成本</p>
        <span className="text-xs text-muted-foreground">
          合计 {formatCost(total, cnyPerUsd)}
        </span>
      </div>
      <div className="mt-3 flex h-16 items-end gap-1.5">
        {points.map((p) => {
          // Min 2% so a zero / tiny day still shows a sliver baseline.
          const h = max > 0 ? Math.max((p.cost_total / max) * 100, 2) : 2;
          return (
            <SimpleTooltip
              key={p.date}
              label={`${weekdayLabel(p.date)} · ${formatCost(p.cost_total, cnyPerUsd)}`}
            >
              <div className="flex flex-1 flex-col items-center gap-1">
                <div className="flex w-full flex-1 items-end">
                  <div
                    className="w-full rounded-full bg-primary"
                    style={{ height: `${h}%` }}
                  />
                </div>
                <span className="text-xs text-muted-foreground">
                  {weekdayLabel(p.date)}
                </span>
              </div>
            </SimpleTooltip>
          );
        })}
      </div>
    </div>
  );
}

/** Ledger system roles → 大众-facing zh labels. Unknown roles fall back to raw. */
const ROLE_LABELS: Record<string, string> = {
  captain: "CEO",
  member: "队员",
  arena: "辩论",
  title: "标题生成",
  memory: "记忆整理",
  vision: "视觉读图",
};

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

/**
 * 本月各角色花销 (§7.3D) — the team payroll grouped by role, the multi-agent
 * differentiator a single-agent tool can't show. ¥ per role is 大众-visible
 * (money is never gated, §7.1); BYOK rows use ≈¥ from cost_estimated_total.
 */
function RolePayroll({
  lines,
  cnyPerUsd,
  estimated = false,
}: {
  lines: Summary["month_by_role"];
  cnyPerUsd: number;
  estimated?: boolean;
}) {
  return (
    <div>
      <p className="text-sm text-foreground">
        {estimated ? "本月各角色估算" : "本月各角色花销"}
      </p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {estimated
          ? "按社区价目/自填单价估算，非上游账单。多 Agent 按角色拆分。"
          : "多 Agent 团队按角色拆分的花销，竞品的单 Agent 做不到。"}
      </p>
      <Card className="mt-3">
        {lines.map((line, i) => {
          const nano = estimated ? line.cost_estimated_total : line.cost_total;
          return (
            <div
              key={line.role}
              className={`flex items-center justify-between px-4 py-2.5 text-sm ${
                i > 0 ? "border-t border-border" : ""
              }`}
            >
              <span className="flex items-center gap-2 text-foreground">
                <span
                  className="size-2 shrink-0 rounded-full"
                  style={{ backgroundColor: agentColorVar(line.role) }}
                  aria-hidden
                />
                <span>
                  {roleLabel(line.role)}
                  <span className="ml-2 text-xs text-muted-foreground">
                    {line.turns} 回合
                  </span>
                </span>
              </span>
              <span className="tabular-nums text-foreground">
                {formatDisplayCost(nano, cnyPerUsd, estimated)}
              </span>
            </div>
          );
        })}
      </Card>
    </div>
  );
}

/** Power breakdown: today's tokens / cache hit rate, plus month cost + requests. */
function UsageDetail({
  summary,
  cnyPerUsd,
  byok,
}: {
  summary: Summary;
  cnyPerUsd: number;
  byok: boolean;
}) {
  const { today, month } = summary;
  const input = today.usage.input;
  const hitRate =
    input > 0 ? Math.round((today.usage.cache_hit / input) * 100) : 0;

  const rows: { label: string; value: string }[] = [
    {
      label: "今日 tokens",
      value: `输入 ${formatCompact(input)} · 输出 ${formatCompact(today.usage.output)}`,
    },
    { label: "今日缓存命中率", value: `${hitRate}%` },
  ];
  if (!byok) {
    rows.push(
      {
        label: "今日成本",
        value: `${formatCost(today.cost.total, cnyPerUsd)}（${formatUsd(today.cost.total)}）`,
      },
      {
        label: "本月成本",
        value: `${formatCost(month.cost.total, cnyPerUsd)}（${formatUsd(month.cost.total)}）`,
      },
    );
  } else {
    rows.push({
      label: "本月 tokens",
      value: `输入 ${formatCompact(month.usage.input)} · 输出 ${formatCompact(month.usage.output)}`,
    });
    const todayEst = today.estimated_cost?.total ?? 0;
    const monthEst = month.estimated_cost?.total ?? 0;
    if (todayEst > 0 || monthEst > 0) {
      rows.push(
        {
          label: "今日估算",
          value: formatDisplayCost(todayEst, cnyPerUsd, true),
        },
        {
          label: "本月估算",
          value: formatDisplayCost(monthEst, cnyPerUsd, true),
        },
      );
    }
  }
  rows.push({
    label: "请求数",
    value: `今日 ${today.requests} · 本月 ${month.requests}`,
  });

  return (
    <Card>
      {rows.map((row, i) => (
        <div
          key={row.label}
          className={`flex items-center justify-between px-4 py-2.5 text-sm ${
            i > 0 ? "border-t border-border" : ""
          }`}
        >
          <span className="text-muted-foreground">{row.label}</span>
          <span className="tabular-nums text-foreground">{row.value}</span>
        </div>
      ))}
    </Card>
  );
}
