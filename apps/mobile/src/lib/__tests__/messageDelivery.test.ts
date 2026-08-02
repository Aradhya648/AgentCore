import { defaultDelivery, isLiveInterruptible } from "@/lib/messageDelivery";
import type { ProjectedTurn } from "@agentcore/protocol-conformance";
import { describe, expect, it } from "vitest";

function bareTurn(over: Partial<ProjectedTurn> = {}): ProjectedTurn {
  return {
    status: "running",
    finishReason: null,
    content: "",
    reasoning: "",
    captainContext: [],
    process: [],
    citations: [],
    evidenceLedger: [],
    citedIds: [],
    agents: [],
    runs: [],
    acts: [],
    progress: { completed: 0, total: 0 },
    interactions: [],
    cost: null,
    debate: null,
    debateRounds: [],
    debatePretrial: null,
    crossExamEnabled: false,
    debateOpening: null,
    teamSynthesisPreview: null,
    deliveryStatus: null,
    turnWarning: null,
    teamNotes: [],
    userInterjections: [],
    ...over,
  };
}

describe("defaultDelivery", () => {
  it("空闲 → steer", () => {
    expect(defaultDelivery({ busy: false })).toBe("steer");
  });

  it("busy（可插）→ steer", () => {
    expect(defaultDelivery({ busy: true, interruptible: true })).toBe("steer");
  });

  it("经典 busy（不可插启发式）→ 仍默认 steer", () => {
    expect(defaultDelivery({ busy: true, interruptible: false })).toBe("steer");
  });
});

describe("isLiveInterruptible", () => {
  it("单聊无团队 → false", () => {
    expect(isLiveInterruptible(bareTurn())).toBe(false);
  });

  it("有 runs → true", () => {
    expect(
      isLiveInterruptible(
        bareTurn({
          runs: [{ id: "r1" }] as ProjectedTurn["runs"],
        }),
      ),
    ).toBe(true);
  });

  it("有插话 → true", () => {
    expect(
      isLiveInterruptible(
        bareTurn({
          userInterjections: [
            {
              interjectionId: "ij1",
              executionId: "e1",
              content: "hi",
              status: "received",
              note: null,
            },
          ],
        }),
      ),
    ).toBe(true);
  });

  it("null → false", () => {
    expect(isLiveInterruptible(null)).toBe(false);
  });
});
