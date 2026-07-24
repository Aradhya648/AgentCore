import { type Execution, hasRevisions, isDebate } from "@/stores/execution";
import { describe, expect, it } from "vitest";

/**
 * Mirrors TurnDetailPage showCompare gate: revisable runs only — never
 * `revisable && !isDebate` (that hid 对比 on mixed multi_agent+debate graphs).
 */
function showCompare(execution: Execution | null | undefined): boolean {
  return !!execution && hasRevisions(execution);
}

describe("TurnDetailPage showCompare gate", () => {
  it("shows compare when revisable even if the graph is a debate", () => {
    const withDebateAndRev = {
      planType: "debate",
      debate: { form: "debate" },
      runs: [
        {
          id: "r1",
          continuesRunId: null,
          stance: "pro",
          group: "debate:main",
        },
        {
          id: "r1b",
          continuesRunId: "r1",
          stance: "pro",
          group: "debate:main",
        },
      ],
    } as unknown as Execution;
    expect(isDebate(withDebateAndRev)).toBe(true);
    expect(hasRevisions(withDebateAndRev)).toBe(true);
    expect(showCompare(withDebateAndRev)).toBe(true);
    // Old buggy gate: revisable && !debate → false
    expect(hasRevisions(withDebateAndRev) && !isDebate(withDebateAndRev)).toBe(
      false,
    );
  });

  it("hides compare when there are no revisable runs", () => {
    const plain = {
      planType: "multi_agent",
      runs: [{ id: "r1", continuesRunId: null }],
    } as unknown as Execution;
    expect(showCompare(plain)).toBe(false);
  });
});
