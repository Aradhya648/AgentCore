import { type UsageSummary, getUsageSummary } from "@/api/usage";
// 用量 (/more/usage) — the account spend dashboard (mirrors desktop UsageSettings).
//
// Leads with quota meters (or a BYOK note when the user runs on their own key), then
// this month's cost and a 7-day trend. Money is formatted from the summary's single
// server-owned FX rate (cny_per_usd) — the client never re-prices. The desktop's
// global「用量明细」Power toggle lives in a UI store there; mobile shows the core
// figures inline.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

function cny(nanoUsd: number, rate: number, estimated = false): string {
  if (nanoUsd <= 0) return "—";
  const yuan = (nanoUsd / 1e9) * rate;
  const body = yuan < 0.01 ? "<¥0.01" : `¥${yuan.toFixed(2)}`;
  return estimated ? `≈${body}` : body;
}

function compact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

export function UsageSettings() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    getUsageSummary()
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : "加载用量失败"))
      .finally(() => setLoading(false));
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: load is stable enough; run once on open
  useEffect(() => {
    load();
  }, []);

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() => navigate("/more")}
        >
          ← 设置
        </button>
        <span>用量</span>
        <button
          type="button"
          className="link"
          onClick={() => load()}
          disabled={loading}
        >
          {loading ? "刷新中…" : "刷新"}
        </button>
      </header>

      <div className="settings-body">
        {!summary && loading && <p className="muted hint">加载中…</p>}
        {!summary && error && (
          <div className="hint">
            <p className="error">{error}</p>
            <button
              type="button"
              onClick={() => load()}
              style={{ marginTop: 12 }}
            >
              重试
            </button>
          </div>
        )}
        {summary && <Dashboard summary={summary} />}
      </div>
    </div>
  );
}

function Dashboard({ summary }: { summary: UsageSummary }) {
  const rate = summary.cny_per_usd;
  const byok = summary.billing_mode === "byok";
  const { today, month, quota } = summary;
  const monthLimit = quota.monthly_cost_nano;
  const monthUsed = month.cost.total;
  // 单日成本 backstop (成本配额与计费 §〇·六 F2) — 与桌面同语义：仅在配了日成本上限时画，
  // 0 = 不限不画。平台翻转后才会 >0（byok/免费档留 0）。
  const dayCostLimit = quota.daily_cost_nano;
  const dayCostUsed = today.cost.total;
  const todayEst = today.estimated_cost?.total ?? 0;
  const monthEst = month.estimated_cost?.total ?? 0;

  return (
    <>
      {byok ? (
        <p className="section-note" style={{ marginBottom: 18 }}>
          当前为「自带 Key」模式：平台不限额。有估算价时显示
          ≈¥（非上游账单），并以 token 用量为主。
        </p>
      ) : (
        <>
          <Meter
            label="本月额度"
            used={monthUsed}
            limit={monthLimit}
            caption={
              monthLimit > 0
                ? `已用 ${cny(monthUsed, rate)} / ${cny(monthLimit, rate)}`
                : `已用 ${cny(monthUsed, rate)} · 不限`
            }
          />
          {dayCostLimit > 0 && (
            <Meter
              label="今日额度"
              used={dayCostUsed}
              limit={dayCostLimit}
              caption={`已用 ${cny(dayCostUsed, rate)} / ${cny(dayCostLimit, rate)}`}
            />
          )}
        </>
      )}

      <div className="section">
        <h2 className="section-title">{byok ? "用量" : "本月成本"}</h2>
        <div className="section-card">
          {!byok && (
            <>
              <div className="payroll-row" style={{ padding: 0 }}>
                <span>本月</span>
                <span className="payroll-cost">
                  {cny(month.cost.total, rate)}
                </span>
              </div>
              <div
                className="payroll-row"
                style={{
                  padding: 0,
                  borderTop: "1px solid var(--border)",
                  paddingTop: 12,
                }}
              >
                <span>今日</span>
                <span className="payroll-cost">
                  {cny(today.cost.total, rate)}
                </span>
              </div>
            </>
          )}
          <div
            className="payroll-row"
            style={{
              padding: 0,
              borderTop: byok ? undefined : "1px solid var(--border)",
              paddingTop: byok ? 0 : 12,
            }}
          >
            <span>今日 tokens</span>
            <span className="payroll-cost">
              输入 {compact(today.usage.input)} · 输出{" "}
              {compact(today.usage.output)}
            </span>
          </div>
          {byok && (
            <div
              className="payroll-row"
              style={{
                padding: 0,
                borderTop: "1px solid var(--border)",
                paddingTop: 12,
              }}
            >
              <span>本月 tokens</span>
              <span className="payroll-cost">
                输入 {compact(month.usage.input)} · 输出{" "}
                {compact(month.usage.output)}
              </span>
            </div>
          )}
          {byok && (todayEst > 0 || monthEst > 0) && (
            <>
              <div
                className="payroll-row"
                style={{
                  padding: 0,
                  borderTop: "1px solid var(--border)",
                  paddingTop: 12,
                }}
              >
                <span>今日估算</span>
                <span className="payroll-cost">
                  {cny(todayEst, rate, true)}
                </span>
              </div>
              <div
                className="payroll-row"
                style={{
                  padding: 0,
                  borderTop: "1px solid var(--border)",
                  paddingTop: 12,
                }}
              >
                <span>本月估算</span>
                <span className="payroll-cost">
                  {cny(monthEst, rate, true)}
                </span>
              </div>
            </>
          )}
        </div>
      </div>

      {summary.recent_daily_cost.some((p) => p.cost_total > 0) && !byok && (
        <CostTrend points={summary.recent_daily_cost} rate={rate} />
      )}
    </>
  );
}

function Meter({
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
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <span className={`meter-pct${near ? " near" : ""}`}>
          {unlimited ? "不限" : `${pct}%`}
        </span>
      </div>
      <div className="meter-track">
        {!unlimited && (
          <div
            className={`meter-fill${near ? " near" : ""}`}
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      <span className="meter-cap">{caption}</span>
    </div>
  );
}

function weekday(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  return `周${["日", "一", "二", "三", "四", "五", "六"][d.getUTCDay()]}`;
}

function CostTrend({
  points,
  rate,
}: {
  points: UsageSummary["recent_daily_cost"];
  rate: number;
}) {
  const max = points.reduce((m, p) => Math.max(m, p.cost_total), 0);
  const total = points.reduce((s, p) => s + p.cost_total, 0);
  return (
    <div className="section">
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <h2 className="section-title">近 7 日成本</h2>
        <span className="meter-cap">合计 {cny(total, rate)}</span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 6,
          height: 72,
          marginTop: 12,
        }}
      >
        {points.map((p) => {
          const h = max > 0 ? Math.max((p.cost_total / max) * 100, 3) : 3;
          return (
            <div
              key={p.date}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 4,
              }}
            >
              <div
                style={{
                  flex: 1,
                  width: "100%",
                  display: "flex",
                  alignItems: "flex-end",
                }}
              >
                <div
                  style={{
                    width: "100%",
                    height: `${h}%`,
                    background: "var(--accent)",
                    borderRadius: 999,
                  }}
                />
              </div>
              <span className="meter-cap">{weekday(p.date)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
