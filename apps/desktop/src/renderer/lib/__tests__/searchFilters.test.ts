import { timeFilterSince } from "@/lib/searchFilters";
import { describe, expect, it } from "vitest";

describe("timeFilterSince", () => {
  // A fixed, mid-day instant so 「今天」(local midnight) is strictly earlier and
  // the rolling windows are exact multiples of a day back.
  const now = new Date("2026-07-08T13:30:00.000Z");

  it("returns undefined for 全部 (no time bound)", () => {
    expect(timeFilterSince("all", now)).toBeUndefined();
  });

  it("今天 anchors to local midnight, not a rolling 24h", () => {
    const since = timeFilterSince("today", now);
    expect(since).toBeDefined();
    const midnight = new Date(since as string);
    // Same calendar day as `now`, at 00:00 local.
    expect(midnight.getFullYear()).toBe(now.getFullYear());
    expect(midnight.getMonth()).toBe(now.getMonth());
    expect(midnight.getDate()).toBe(now.getDate());
    expect(midnight.getHours()).toBe(0);
    expect(midnight.getMinutes()).toBe(0);
    expect(midnight.getSeconds()).toBe(0);
    expect(midnight.getTime()).toBeLessThan(now.getTime());
  });

  it("近 7 天 is exactly 7×24h before now", () => {
    const since = timeFilterSince("7d", now);
    expect(new Date(since as string).getTime()).toBe(
      now.getTime() - 7 * 24 * 60 * 60 * 1000,
    );
  });

  it("近 30 天 is exactly 30×24h before now", () => {
    const since = timeFilterSince("30d", now);
    expect(new Date(since as string).getTime()).toBe(
      now.getTime() - 30 * 24 * 60 * 60 * 1000,
    );
  });
});
