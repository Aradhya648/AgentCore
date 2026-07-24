import {
  COST_ESTIMATE_LABEL,
  formatCompact,
  formatCost,
  formatCostCaption,
  formatDateDivider,
  formatDisplayCost,
  formatDisplayUsd,
  formatMessageTime,
  formatMessageTimeOfDay,
  formatUsd,
  pickCostMoney,
} from "@/lib/format";
import { describe, expect, it, vi } from "vitest";

// 1 USD = 1e9 nano-USD (ledger canonical unit).
const USD = 1_000_000_000;

describe("formatCost", () => {
  it("converts nano-USD to CNY via the rate, rounded to fen", () => {
    // 0.0166667 USD × 7.2 ≈ ¥0.12
    expect(formatCost(16_666_667, 7.2)).toBe("¥0.12");
    expect(formatCost(USD, 7.2)).toBe("¥7.20");
  });

  it("shows「—」for zero / negative (无花销，不显 ¥0.00) — §7.5", () => {
    expect(formatCost(0, 7.2)).toBe("—");
    expect(formatCost(-5, 7.2)).toBe("—");
  });

  it("shows「<¥0.01」for a cost that rounds below one fen", () => {
    // 1000 nano = 1e-6 USD × 7.2 = 7.2e-6 元 < 0.01
    expect(formatCost(1000, 7.2)).toBe("<¥0.01");
  });

  it("tracks the rate (单一来源，前端不写死)", () => {
    // Same nano amount, a different FX rate → a different yuan figure.
    expect(formatCost(USD, 10)).toBe("¥10.00");
  });
});

describe("formatUsd", () => {
  it("formats nano-USD as $ with 4 decimals (power 面)", () => {
    expect(formatUsd(12_300_000)).toBe("$0.0123");
    expect(formatUsd(USD)).toBe("$1.0000");
  });

  it("shows「—」for zero / negative — §7.5", () => {
    expect(formatUsd(0)).toBe("—");
    expect(formatUsd(-1)).toBe("—");
  });

  it("shows「<$0.0001」for a positive cost below the display floor", () => {
    // 1000 nano = 1e-6 USD < 0.0001
    expect(formatUsd(1000)).toBe("<$0.0001");
  });
});

describe("formatDisplayCost / pickCostMoney (BYOK ≈)", () => {
  it("prefixes ≈ only for estimates; billed stays plain ¥", () => {
    expect(formatDisplayCost(USD, 7.2, false)).toBe("¥7.20");
    expect(formatDisplayCost(USD, 7.2, true)).toBe("≈¥7.20");
    expect(formatDisplayCost(0, 7.2, true)).toBe("—");
    expect(formatDisplayUsd(USD, true)).toBe("≈$1.0000");
  });

  it("picks billed total over estimated_total", () => {
    expect(pickCostMoney({ total: 100, estimated_total: 999 })).toEqual({
      nano: 100,
      estimated: false,
    });
    expect(pickCostMoney({ total: 0, estimated_total: 999 })).toEqual({
      nano: 999,
      estimated: true,
    });
    expect(pickCostMoney({ total: 0 })).toEqual({
      nano: 0,
      estimated: false,
    });
  });

  it("marks user_defined pricing as BYOK estimate even when total > 0", () => {
    expect(
      pickCostMoney({ total: 100, pricing_source: "user_defined" }),
    ).toEqual({ nano: 100, estimated: true });
  });

  it("appends 自带密钥·估算 caption for estimates", () => {
    expect(formatCostCaption(USD, 7.2, true)).toBe(
      `≈¥7.20 ${COST_ESTIMATE_LABEL}`,
    );
    expect(formatCostCaption(USD, 7.2, false)).toBe("¥7.20");
  });
});

describe("formatCompact", () => {
  it("keeps small counts verbatim, abbreviates k then M (用量大数)", () => {
    expect(formatCompact(0)).toBe("0");
    expect(formatCompact(820)).toBe("820");
    expect(formatCompact(8200)).toBe("8.2k");
    expect(formatCompact(820_000)).toBe("820.0k");
    expect(formatCompact(2_000_000)).toBe("2.0M");
  });
});

describe("formatMessageTimeOfDay", () => {
  it("returns HH:MM for a valid ISO timestamp", () => {
    expect(formatMessageTimeOfDay("2026-07-05T14:32:00")).toMatch(/14:32/);
  });
});

describe("formatDateDivider", () => {
  it("labels today, yesterday, same year, and cross-year", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T12:00:00"));

    expect(formatDateDivider("2026-07-05T08:00:00")).toBe("今天");
    expect(formatDateDivider("2026-07-04T08:00:00")).toBe("昨天");
    expect(formatDateDivider("2026-03-15T08:00:00")).toBe("3月15日");
    expect(formatDateDivider("2025-03-15T08:00:00")).toBe("2025年3月15日");

    vi.useRealTimers();
  });
});

describe("formatMessageTime", () => {
  it("adds day context for list previews", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-05T12:00:00"));

    expect(formatMessageTime("2026-07-05T08:30:00")).toMatch(/08:30/);
    expect(formatMessageTime("2026-07-04T08:30:00")).toBe("昨天 08:30");

    vi.useRealTimers();
  });
});
