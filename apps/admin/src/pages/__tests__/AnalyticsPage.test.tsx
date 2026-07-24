// @vitest-environment jsdom
/**
 * Render tests for the admin 分析 page (AUD-012 测试覆盖补强 · admin 半).
 *
 * AnalyticsPage fuses two lenses behind one segmented control: 成本 (fetchUsageSummary) and
 * 健康 (fetchObservabilitySummary), plus a 会话复盘 drill-in. These pin the per-lens render,
 * the BYOK cost framing, the lens switch (which triggers a fresh fetch), and both replay
 * entry points (error-row click + the ID form) with the services + trend charts mocked. The
 * leading block comment keeps the @vitest-environment directive file-leading.
 */

import { AnalyticsPage } from "@/pages/AnalyticsPage";
import {
  type AdminObservabilitySummary,
  type TurnHealthWindow,
  type TurnMetricLine,
  fetchObservabilitySummary,
} from "@/services/adminObservability";
import {
  type AdminUsageSummary,
  type UsageWindow,
  fetchUsageSummary,
} from "@/services/adminUsage";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/adminUsage", () => ({ fetchUsageSummary: vi.fn() }));
vi.mock("@/services/adminObservability", () => ({
  fetchObservabilitySummary: vi.fn(),
}));
// AuditSummaryWidget fires an unmocked fetch whose rejection lands after teardown
// (window is gone) — pin it to a never-resolving promise to kill the unhandled error.
vi.mock("@/services/adminAgentAudit", () => ({
  fetchAuditSummary: vi.fn(() => new Promise(() => {})),
}));
// Trend charts are not under test — stub them to keep the test on the page's own layout.
vi.mock("@/components/charts", () => ({
  CostTrendBars: () => <div data-testid="cost-trend" />,
  TurnTrendBars: () => <div data-testid="turn-trend" />,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function usageWindow(cnyTotal: number, requests: number): UsageWindow {
  return {
    cost: {
      cached: 0,
      cny_total: cnyTotal,
      currency: "USD",
      input: 0,
      output: 0,
      total: 0,
      pricing_source: "curated",
    },
    usage: { cache_hit: 0, cache_miss: 0, input: 0, output: 0, reasoning: 0 },
    requests,
  };
}

function usageSummary(p?: Partial<AdminUsageSummary>): AdminUsageSummary {
  return {
    billing_mode: "platform",
    cny_per_usd: 7,
    today: usageWindow(12.5, 3),
    month: usageWindow(88, 9),
    month_by_role: [],
    month_by_model: [],
    month_by_user: [
      {
        user_id: "u1",
        username: "alice",
        display_name: "Alice",
        cost_total: 1_000_000_000,
        turns: 5,
      },
    ],
    recent_daily_cost: [],
    ...p,
  };
}

function healthWindow(p?: Partial<TurnHealthWindow>): TurnHealthWindow {
  return {
    avg_duration_ms: 0,
    avg_rounds: 1,
    delegated_rate: 0,
    delegated_turns: 0,
    error_rate: 0,
    errors: 0,
    escalations: 0,
    first_plan_survival_rate: 0,
    input_tokens: 0,
    output_tokens: 0,
    p95_duration_ms: 0,
    revises: 0,
    scope_signals: 0,
    turns: 0,
    ...p,
  };
}

function obsSummary(p?: Partial<AdminObservabilitySummary>): AdminObservabilitySummary {
  return {
    today: healthWindow(),
    week: healthWindow(),
    recent_daily: [],
    recent_errors: [],
    ...p,
  };
}

function errLine(
  p: Partial<TurnMetricLine> & { turn_id: string; conversation_id: string },
): TurnMetricLine {
  return {
    agent_id: null,
    created_at: "2026-06-30T10:00:00Z",
    delegated: false,
    duration_ms: 1200,
    error: "boom",
    finish_reason: "error",
    input_tokens: 0,
    kind: "chat",
    output_tokens: 0,
    rounds: 1,
    status: "error",
    trace_id: "trace123",
    user_id: "u1",
    workers: 0,
    ...p,
  };
}

/** Probe route so a navigate("/replay/:id") drill-in is asserted by rendered text. */
function ReplayProbe() {
  const { id } = useParams<{ id: string }>();
  return <div>复盘页 {id}</div>;
}

function renderAnalytics(initial = "/analytics/cost") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/analytics/:segment" element={<AnalyticsPage />} />
        <Route path="/replay/:id" element={<ReplayProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AnalyticsPage", () => {
  it("renders the 成本 lens: window totals + top spenders + trend", async () => {
    vi.mocked(fetchUsageSummary).mockResolvedValue(usageSummary());
    renderAnalytics("/analytics/cost");
    expect(await screen.findByText("今日总成本")).toBeTruthy();
    expect(screen.getByText("本月总成本")).toBeTruthy();
    expect(screen.getByText("¥12.50")).toBeTruthy(); // today cny_total = 12.5
    expect(screen.getByText("Alice")).toBeTruthy(); // top spender row
    expect(screen.getByTestId("cost-trend")).toBeTruthy();
    expect(fetchUsageSummary).toHaveBeenCalledTimes(1);
  });

  it("shows the BYOK framing when billing_mode is byok", async () => {
    vi.mocked(fetchUsageSummary).mockResolvedValue(
      usageSummary({ billing_mode: "byok" }),
    );
    renderAnalytics("/analytics/cost");
    expect(await screen.findByText(/BYOK/)).toBeTruthy();
  });

  it("switches to the 健康 lens and loads observability on demand", async () => {
    vi.mocked(fetchUsageSummary).mockResolvedValue(usageSummary());
    vi.mocked(fetchObservabilitySummary).mockResolvedValue(
      obsSummary({ today: healthWindow({ turns: 20, errors: 1, error_rate: 0.05 }) }),
    );
    renderAnalytics("/analytics/cost");
    await screen.findByText("今日总成本"); // cost lens loaded first
    expect(fetchObservabilitySummary).not.toHaveBeenCalled(); // only the active lens fetches
    fireEvent.click(screen.getByRole("button", { name: "健康" }));
    expect(await screen.findByText("今日回合数")).toBeTruthy();
    expect(screen.getByTestId("turn-trend")).toBeTruthy();
    expect(fetchObservabilitySummary).toHaveBeenCalledTimes(1);
  });

  it("drills from an error row into 会话复盘", async () => {
    vi.mocked(fetchObservabilitySummary).mockResolvedValue(
      obsSummary({
        recent_errors: [errLine({ turn_id: "t1", conversation_id: "conv-9", error: "炸了" })],
      }),
    );
    renderAnalytics("/analytics/health");
    fireEvent.click(await screen.findByText("炸了"));
    expect(await screen.findByText(/复盘页 conv-9/)).toBeTruthy();
  });

  it("opens 复盘 from the 会话 ID form", async () => {
    vi.mocked(fetchUsageSummary).mockResolvedValue(usageSummary());
    renderAnalytics("/analytics/cost");
    await screen.findByText("今日总成本");
    fireEvent.change(screen.getByPlaceholderText("会话 ID 复盘…"), {
      target: { value: "conv-42" },
    });
    fireEvent.click(screen.getByRole("button", { name: "复盘" }));
    expect(await screen.findByText(/复盘页 conv-42/)).toBeTruthy();
  });
});
