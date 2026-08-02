import {
  COST_ESTIMATE_LABEL,
  formatBytes,
  formatBytesPerSecond,
  formatCompact,
  formatCost,
  formatCostCaption,
  formatDateDivider,
  formatDisplayCost,
  formatDownloadProgress,
  formatMessageTime,
  formatMessageTimeOfDay,
  pickCostMoney,
} from "@/lib/format";
import { describe, expect, it, vi } from "vitest";

// 1 元 = 1e9 nano-CNY (ledger canonical unit).
const YUAN = 1_000_000_000;

describe("formatDownloadProgress", () => {
  it("joins percent, size, and speed", () => {
    expect(
      formatDownloadProgress({
        percent: 42,
        transferred: 83_886_080,
        total: 198_180_864,
        bytesPerSecond: 524_288,
      }),
    ).toBe("42% · 80 MB / 189 MB · 512 KB/s");
  });

  it("omits size and speed when unknown", () => {
    expect(
      formatDownloadProgress({
        percent: 10,
        transferred: 0,
        total: 0,
        bytesPerSecond: 0,
      }),
    ).toBe("10%");
  });
});

describe("formatBytesPerSecond", () => {
  it("returns null for non-positive rates", () => {
    expect(formatBytesPerSecond(0)).toBeNull();
    expect(formatBytesPerSecond(-1)).toBeNull();
  });

  it("appends /s to formatBytes", () => {
    expect(formatBytesPerSecond(1024)).toBe(`${formatBytes(1024)}/s`);
  });
});

describe("formatCost", () => {
  it("converts nano-CNY to ¥, rounded to fen", () => {
    expect(formatCost(120_000_000)).toBe("¥0.12");
    expect(formatCost(YUAN)).toBe("¥1.00");
  });

  it("shows「—」for zero / negative (无花销，不显 ¥0.00) — §7.5", () => {
    expect(formatCost(0)).toBe("—");
    expect(formatCost(-5)).toBe("—");
  });

  it("shows「<¥0.01」for a cost that rounds below one fen", () => {
    expect(formatCost(1000)).toBe("<¥0.01");
  });
});

describe("formatDisplayCost / pickCostMoney (BYOK ≈)", () => {
  it("prefixes ≈ only for estimates; billed stays plain ¥", () => {
    expect(formatDisplayCost(YUAN, false)).toBe("¥1.00");
    expect(formatDisplayCost(YUAN, true)).toBe("≈¥1.00");
    expect(formatDisplayCost(0, true)).toBe("—");
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

  it("treats total > 0 as billed (not estimate), even with pricing_source", () => {
    expect(pickCostMoney({ total: 100, pricing_source: "curated" })).toEqual({
      nano: 100,
      estimated: false,
    });
  });

  it("appends 自带密钥·估算 caption for estimates", () => {
    expect(formatCostCaption(YUAN, true)).toBe(`≈¥1.00 ${COST_ESTIMATE_LABEL}`);
    expect(formatCostCaption(YUAN, false)).toBe("¥1.00");
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
