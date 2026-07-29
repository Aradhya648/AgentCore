/**
 * EscalationCards 列表序 / raised 收起规则（对齐 faceBudget：待拍板 > raised）。
 */
import {
  escalationListRank,
  shouldCollapseRaised,
} from "@/components/chat/EscalationCard";
import { describe, expect, it } from "vitest";

describe("escalationListRank", () => {
  it("orders pending before settled before raised", () => {
    const statuses = [
      "raised",
      "resolved",
      "pending",
      "assumed",
      "timed_out",
      "raised",
    ] as const;
    const ordered = [...statuses].sort(
      (a, b) => escalationListRank(a) - escalationListRank(b),
    );
    expect(ordered).toEqual([
      "pending",
      "resolved",
      "assumed",
      "timed_out",
      "raised",
      "raised",
    ]);
  });
});

describe("shouldCollapseRaised", () => {
  it("collapses when two or more raised", () => {
    expect(shouldCollapseRaised(2, 0)).toBe(true);
    expect(shouldCollapseRaised(1, 0)).toBe(false);
  });

  it("collapses a single raised when there is also pending", () => {
    expect(shouldCollapseRaised(1, 1)).toBe(true);
    expect(shouldCollapseRaised(0, 1)).toBe(false);
  });
});
