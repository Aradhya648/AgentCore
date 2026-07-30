// @vitest-environment jsdom
/**
 * Render tests for mobile 用量 (More → /more/usage), focused on the 今日额度 meter
 * added for the platform billing flip (成本配额与计费 §〇·六 F2). Mirrors desktop
 * semantics: the daily-cost meter renders only when a daily cost cap is configured
 * (quota.daily_cost_nano > 0); 0 = 不限不画. Service mocked so no real HTTP.
 */
import type {
  CostBreakdown,
  QuotaStatus,
  UsageBreakdown,
  UsageSummary,
  UsageWindow,
} from "@/api/usage";
import { getUsageSummary } from "@/api/usage";
import { UsageSettings } from "@/pages/more/UsageSettings";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/usage", () => ({ getUsageSummary: vi.fn() }));

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => vi.fn() };
});

const mockGet = vi.mocked(getUsageSummary);

afterEach(cleanup);
beforeEach(() => {
  mockGet.mockReset();
});

function usageBd(): UsageBreakdown {
  return { input: 0, output: 0, reasoning: 0, cache_hit: 0, cache_miss: 0 };
}

function costBd(total = 0): CostBreakdown {
  return {
    input: 0,
    cached: 0,
    output: 0,
    total,
    currency: "USD",
    cny_total: 0,
    pricing_source: "curated",
  };
}

function usageWindow(costTotal: number): UsageWindow {
  return { usage: usageBd(), cost: costBd(costTotal), requests: 1 };
}

function makeSummary(quota: Partial<QuotaStatus>): UsageSummary {
  return {
    today: usageWindow(2_000_000_000),
    month: usageWindow(3_000_000_000),
    recent_daily_cost: [],
    quota: {
      daily_tokens: 0,
      monthly_cost_nano: 10_000_000_000,
      daily_cost_nano: 0,
      daily_requests: 0,
      ...quota,
    },
    cny_per_usd: 7,
    billing_mode: "platform",
  };
}

describe("UsageSettings 今日额度 meter", () => {
  it("renders the daily-cost meter when a daily cost cap is configured", async () => {
    mockGet.mockResolvedValue(makeSummary({ daily_cost_nano: 5_000_000_000 }));
    render(<UsageSettings />);

    await waitFor(() => expect(screen.getByText("本月额度")).toBeTruthy());
    expect(screen.getByText("今日额度")).toBeTruthy();
  });

  it("hides the daily-cost meter when the cap is 0 (不限不画)", async () => {
    mockGet.mockResolvedValue(makeSummary({ daily_cost_nano: 0 }));
    render(<UsageSettings />);

    await waitFor(() => expect(screen.getByText("本月额度")).toBeTruthy());
    expect(screen.queryByText("今日额度")).toBeNull();
  });
});
