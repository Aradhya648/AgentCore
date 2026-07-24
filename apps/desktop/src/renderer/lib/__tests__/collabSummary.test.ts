import { formatCollabSummary } from "@/lib/collabSummary";
import { describe, expect, it } from "vitest";

describe("formatCollabSummary", () => {
  it("returns null when collab is missing or all orchestration signals are zero", () => {
    expect(formatCollabSummary(undefined)).toBeNull();
    expect(
      formatCollabSummary({
        boundary_yields: 0,
        scope_signals: 0,
        revises: 0,
        escalations: 0,
      }),
    ).toBeNull();
  });

  it("formats only non-zero orchestration signals", () => {
    expect(
      formatCollabSummary({
        boundary_yields: 1,
        scope_signals: 0,
        revises: 2,
        escalations: 0,
      }),
    ).toBe("纠偏 1 次 · 唤回 2 次");
  });

  it("ignores audit_drops (diagnostic-only)", () => {
    expect(
      formatCollabSummary({
        boundary_yields: 0,
        scope_signals: 0,
        revises: 0,
        escalations: 0,
        audit_drops: 3,
      }),
    ).toBeNull();
  });
});
